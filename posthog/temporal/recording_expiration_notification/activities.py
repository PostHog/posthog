import json
from datetime import datetime
from uuid import uuid4

from django.db.models import Q

import pytz
from temporalio import activity

from posthog.email import EmailMessage
from posthog.models.event import Team as TeamModel
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User as UserModel
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents, ttl_days
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.recording_expiration_notification.types import Notification, Organization, Recording, Team

LOGGER = get_write_only_logger()

TTL_THRESHOLD = 5  # days


@activity.defn(name="query-organizations")
async def query_organizations() -> list[Organization]:
    async with Heartbeater():
        logger = LOGGER.bind()

        logger.info("Querying organizations...")

        organization_map: dict[str, Organization] = {}

        async for team in (
            TeamModel.objects.select_related("organization")
            .exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True))
            .only("id", "name", "organization__id", "organization__name", "organization__available_product_features")
        ):
            organization_id = str(team.organization_id)

            organization = organization_map.get(
                organization_id,
                Organization(
                    organization_id=organization_id,
                    name=team.organization.name,
                    teams=[],
                ),
            )

            organization.teams.append(
                Team(
                    team_id=team.id,
                    name=team.name,
                    ttl_days=await database_sync_to_async(ttl_days)(team),
                    recordings=[],
                )
            )

            organization_map[organization_id] = organization

        return list(organization_map.values())


def _parse_session_query_response(raw_response: bytes) -> list[Recording]:
    if len(raw_response) == 0:
        raise Exception("Got empty response from ClickHouse.")

    try:
        result = json.loads(raw_response)
        rows = result["data"]
        return [
            Recording(session_id=session["session_id"], recording_ttl=int(session["recording_ttl"])) for session in rows
        ]
    except json.JSONDecodeError as e:
        raise Exception("Unable to parse JSON response from ClickHouse.") from e
    except KeyError as e:
        raise Exception("Got malformed JSON response from ClickHouse.") from e


@activity.defn(name="query-recordings")
async def query_recordings(batch: list[Organization]) -> list[Organization]:
    async with Heartbeater():
        logger = LOGGER.bind()

        logger.info("Querying recordings...")

        async with get_client() as client:
            for organization in batch:
                for team in organization.teams:
                    query: str = SessionReplayEvents.get_soon_to_expire_sessions_query(format="JSON")

                    parameters = {
                        "team_id": team.team_id,
                        "python_now": datetime.now(pytz.timezone("UTC")),
                        "ttl_days": team.ttl_days,
                        "ttl_threshold": TTL_THRESHOLD,
                        "limit": 100,
                    }

                    ch_query_id = str(uuid4())
                    logger.info(f"Querying ClickHouse with query_id: {ch_query_id}")

                    raw_response: bytes = b""
                    async with client.aget_query(
                        query=query, query_parameters=parameters, query_id=ch_query_id
                    ) as ch_response:
                        raw_response = await ch_response.content.read()

                    team.recordings = _parse_session_query_response(raw_response)

        return batch


async def filter_teams(user: UserModel, teams: list[Team]) -> list[Team]:
    user_team_ids: list[int] = await database_sync_to_async(user.accessible_teams)()
    return list(filter(lambda t: t.id in user_team_ids, teams))


@activity.defn(name="generate-notifications")
async def generate_notifications(organization: Organization) -> list[Notification]:
    async with Heartbeater():
        logger = LOGGER.bind()

        expiry_count = sum([len(team.recordings) for team in organization.teams])

        if expiry_count == 0:
            return []

        logger.info("Querying users...")

        notifications: list[Notification] = []

        async for membership in (
            OrganizationMembership.objects.filter(organization_id=organization.organization_id)
            .select_related("user")
            .only("user__uuid", "user__email", "user__first_name", "user__partial_notification_settings")
        ):
            user = membership.user

            if user.notification_settings.get("recording_expiration_notification"):
                filtered_teams = await filter_teams(user, organization.teams)

                if filtered_teams:
                    notifications.append(
                        Notification(
                            user_uuid=user.uuid,
                            user_email=user.email,
                            # user_email="tue@posthog.com",
                            user_first_name=user.first_name,
                            teams=filtered_teams,
                        )
                    )

        return notifications


@activity.defn(name="send-notifications")
async def send_notifications(notifications: list[Notification]) -> None:
    async with Heartbeater():
        logger = LOGGER.bind()
        logger.info(notifications)

        for notification in notifications:
            logger.info("making email")
            try:
                message = await database_sync_to_async(EmailMessage)(
                    use_http=True,
                    campaign_key=f"canary_email_{notification.user_uuid}-{datetime.now().timestamp()}",
                    template_name="canary_email",
                    subject="Testing notifications",
                    template_context={
                        "user_name": notification.user_first_name,
                        "user_email": notification.user_email,
                        "site_url": "http://localhost:8010",
                    },
                )
            except Exception as e:
                logger.info(e)

            logger.info("adding recipient")
            message.add_recipient(notification.user_email)
            logger.info("sending email")
            message.send()
