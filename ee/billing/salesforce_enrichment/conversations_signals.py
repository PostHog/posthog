"""Conversations Slack signals aggregation for Salesforce enrichment."""

import datetime as dt
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Case, Count, DateTimeField, Exists, Max, Min, OuterRef, Q, QuerySet, UUIDField, When
from django.db.models.functions import Cast, Coalesce

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from posthog.models.organization import OrganizationMembership
from posthog.temporal.common.logger import get_logger

from products.conversations.backend.models import TeamConversationsSlackConfig, Ticket
from products.conversations.backend.models.constants import Channel

LOGGER = get_logger(__name__)
MAX_SLACK_MEMBER_PAGES = 100
_UUID_REGEX = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


@dataclass
class ConversationsSlackSignals:
    """Slack support signals for a single PostHog organization."""

    posthog_organization_id: str
    slack_channel_url: str | None
    slack_issue_count: int
    slack_user_count: int | None
    last_slack_activity: dt.datetime | None
    most_recent_support_ticket_url: str | None


def build_slack_channel_url(slack_channel_id: str, slack_team_id: str | None = None) -> str:
    """Build a stable Slack channel URL from Slack IDs."""
    if slack_team_id:
        return f"https://app.slack.com/client/{slack_team_id}/{slack_channel_id}"
    return f"https://app.slack.com/archives/{slack_channel_id}"


def build_support_ticket_url(team_id: int, ticket_number: int) -> str:
    return f"{settings.SITE_URL.rstrip('/')}/project/{team_id}/support/tickets/{ticket_number}"


def _get_slack_bot_token(slack_team_id: str | None, team_id: int | None) -> str | None:
    """Resolve the Slack bot token that can read a channel.

    The bot lives in the channel's Slack workspace, so match the config by
    ``slack_team_id`` (unique per workspace) first and fall back to the
    representative PostHog team only when the workspace id is unknown.
    """
    configs = TeamConversationsSlackConfig.objects.filter(slack_bot_token__isnull=False).only("slack_bot_token")

    config = configs.filter(slack_team_id=slack_team_id).first() if slack_team_id else None
    if config is None and team_id is not None:
        config = configs.filter(team_id=team_id).first()

    if not config or not config.slack_bot_token:
        return None
    return str(config.slack_bot_token)


def fetch_slack_channel_user_count(team_id: int, slack_channel_id: str, slack_team_id: str | None = None) -> int | None:
    """Fetch the current Slack channel member count using the channel's support bot token."""
    bot_token = _get_slack_bot_token(slack_team_id, team_id)
    if not bot_token:
        return None

    client = WebClient(token=bot_token)
    cursor: str | None = None
    user_count = 0

    for _ in range(MAX_SLACK_MEMBER_PAGES):
        try:
            response = client.conversations_members(
                channel=slack_channel_id,
                cursor=cursor,
                limit=1000,
            )
        except SlackApiError as e:
            LOGGER.warning(
                "slack_channel_user_count_fetch_failed",
                team_id=team_id,
                slack_channel_id=slack_channel_id,
                error=e.response.get("error"),
            )
            return None
        except Exception as e:
            LOGGER.warning(
                "slack_channel_user_count_fetch_error",
                team_id=team_id,
                slack_channel_id=slack_channel_id,
                error=str(e),
            )
            return None

        members = response.get("members") or []
        user_count += len(members)

        response_metadata = response.get("response_metadata") or {}
        cursor = response_metadata.get("next_cursor") or None
        if not cursor:
            return user_count

    LOGGER.warning(
        "slack_channel_user_count_too_many_pages",
        team_id=team_id,
        slack_channel_id=slack_channel_id,
        max_pages=MAX_SLACK_MEMBER_PAGES,
    )
    return None


def _activity_at() -> Coalesce:
    """Most recent activity timestamp for a ticket, preferring the newest available signal."""
    return Coalesce("last_message_at", "updated_at", "created_at", output_field=DateTimeField())


def _tickets_with_verified_org() -> QuerySet[Ticket]:
    """Tickets whose organization attribution is confirmed through a trusted path.

    ``Ticket.organization_id`` can be stamped from an authoritative
    ``OrganizationMembership`` lookup, but also from analytics ``$groups``,
    which are customer-supplied and spoofable. Before an org is used as a
    Salesforce Account key, re-verify it here: the ticket's customer identity
    (the widget's real distinct_id, or the provider-supplied email that the
    Slack/Teams/email channels store in ``distinct_id``/``email_from``) must
    belong to a member of that organization, and that identity must carry a
    positive attestation (``identity_verified=True``).
    """
    membership_for_ticket_org = OrganizationMembership.objects.filter(
        organization_id=OuterRef("organization_uuid")
    ).filter(
        Q(user__distinct_id=OuterRef("distinct_id"))
        | Q(user__email__iexact=OuterRef("distinct_id"))
        | Q(user__email__iexact=OuterRef("email_from"))
    )
    return (
        # organization_id is free text (analytics-derived values are arbitrary), so
        # guard the uuid cast with CASE — an unguarded cast would abort the whole
        # query on the first malformed row. Comparing as uuid also lets the
        # membership organization_id index anchor the EXISTS.
        Ticket.objects.annotate(
            organization_uuid=Case(
                When(organization_id__regex=_UUID_REGEX, then=Cast("organization_id", output_field=UUIDField())),
                output_field=UUIDField(),
            )
        ).filter(Exists(membership_for_ticket_org), identity_verified=True)
    )


def _fetch_slack_channel_aggregate_rows(org_ids: list[str]) -> list[dict[str, object]]:
    if not org_ids:
        return []

    return list(
        _tickets_with_verified_org()
        .filter(
            channel_source=Channel.SLACK,
            organization_id__in=org_ids,
            slack_channel_id__isnull=False,
        )
        .exclude(slack_channel_id="")
        .annotate(activity_at=_activity_at())
        # Slack channel IDs are only unique within a workspace, so group by
        # (org, workspace, channel) to avoid merging unrelated channels.
        .values("organization_id", "slack_team_id", "slack_channel_id")
        .annotate(
            representative_team_id=Min("team_id"),
            slack_issue_count=Count("id"),
            last_slack_activity=Max("activity_at"),
        )
        .order_by(
            "organization_id",
            "-last_slack_activity",
            "-slack_issue_count",
            "slack_channel_id",
            "slack_team_id",
        )
    )


def _fetch_latest_support_ticket_rows(org_ids: list[str]) -> list[dict[str, object]]:
    if not org_ids:
        return []

    return list(
        _tickets_with_verified_org()
        .filter(organization_id__in=org_ids)
        .annotate(activity_at=_activity_at())
        .values("organization_id", "team_id", "ticket_number", "activity_at")
        .order_by("organization_id", "-activity_at", "-ticket_number")
        .distinct("organization_id")
    )


def aggregate_conversations_slack_signals_for_orgs(
    org_ids: list[str],
    *,
    include_slack_user_count: bool = True,
) -> dict[str, ConversationsSlackSignals]:
    """Aggregate Conversations Slack signals for organizations.

    Only tickets with verified org attribution count (see
    ``_tickets_with_verified_org``). If an organization has multiple Slack
    channels, choose the most recently active workspace-scoped channel, then
    tie-break by ticket count and channel ID. Salesforce exposes a single
    Slack channel field, so the issue/user/activity stats are for that
    representative channel.
    """
    if not org_ids:
        return {}

    LOGGER.info("fetching_conversations_slack_signals", org_count=len(org_ids))
    rows = _fetch_slack_channel_aggregate_rows(org_ids)
    latest_ticket_rows = _fetch_latest_support_ticket_rows(org_ids)

    selected_rows: dict[str, dict[str, object]] = {}
    for row in rows:
        org_id = str(row["organization_id"])
        if org_id not in selected_rows:
            selected_rows[org_id] = row

    selected_latest_ticket_rows: dict[str, dict[str, object]] = {}
    for row in latest_ticket_rows:
        org_id = str(row["organization_id"])
        if org_id not in selected_latest_ticket_rows:
            selected_latest_ticket_rows[org_id] = row

    result: dict[str, ConversationsSlackSignals] = {}
    for org_id in sorted(set(selected_rows) | set(selected_latest_ticket_rows)):
        row = selected_rows.get(org_id, {})
        slack_channel_id_value = row.get("slack_channel_id")
        slack_channel_id = (
            slack_channel_id_value if isinstance(slack_channel_id_value, str) and slack_channel_id_value else None
        )

        slack_team_id_value = row.get("slack_team_id")
        slack_team_id = slack_team_id_value if isinstance(slack_team_id_value, str) and slack_team_id_value else None

        team_id_value = row.get("representative_team_id")
        team_id = int(team_id_value) if isinstance(team_id_value, int) else None

        slack_user_count = (
            fetch_slack_channel_user_count(team_id, slack_channel_id, slack_team_id)
            if include_slack_user_count and team_id is not None and slack_channel_id is not None
            else None
        )

        last_slack_activity_value = row.get("last_slack_activity")
        last_slack_activity = last_slack_activity_value if isinstance(last_slack_activity_value, dt.datetime) else None

        latest_ticket_row = selected_latest_ticket_rows.get(org_id, {})
        ticket_team_id_value = latest_ticket_row.get("team_id")
        ticket_number_value = latest_ticket_row.get("ticket_number")
        most_recent_support_ticket_url = (
            build_support_ticket_url(int(ticket_team_id_value), int(ticket_number_value))
            if isinstance(ticket_team_id_value, int) and isinstance(ticket_number_value, int)
            else None
        )

        slack_issue_count_value = row.get("slack_issue_count")
        slack_issue_count = slack_issue_count_value if isinstance(slack_issue_count_value, int) else 0

        result[org_id] = ConversationsSlackSignals(
            posthog_organization_id=org_id,
            slack_channel_url=(
                build_slack_channel_url(slack_channel_id, slack_team_id) if slack_channel_id is not None else None
            ),
            slack_issue_count=slack_issue_count,
            slack_user_count=slack_user_count,
            last_slack_activity=last_slack_activity,
            most_recent_support_ticket_url=most_recent_support_ticket_url,
        )

    LOGGER.info("fetched_conversations_slack_signals", org_count=len(org_ids), signals_found=len(result))
    return result
