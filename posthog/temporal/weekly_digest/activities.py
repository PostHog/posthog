from collections.abc import Callable
from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

import redis.asyncio as redis
from posthoganalytics import Posthog
from pydantic import ValidationError
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.models.messaging import MessagingRecord, get_email_hash
from posthog.ph_client import get_client as get_ph_client
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX
from posthog.sync import database_sync_to_async
from posthog.tasks.email import NotificationSetting, should_send_notification
from posthog.temporal.common.clickhouse import get_client as get_ch_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.weekly_digest.keys import TeamDataKey, UserDataKey, org_digest_key, team_data_key, user_data_key
from posthog.temporal.weekly_digest.queries import (
    query_experiments_completed,
    query_experiments_launched,
    query_new_dashboards,
    query_new_event_definitions,
    query_new_external_data_sources,
    query_new_feature_flags,
    query_org_members,
    query_org_teams,
    query_orgs_for_digest,
    query_saved_filters,
    query_surveys_launched,
    query_teams_for_digest,
    query_user_product_suggestions,
    queryset_to_list,
)
from posthog.temporal.weekly_digest.types import (
    ClickHouseResponse,
    CommonInput,
    DashboardList,
    DigestProductSuggestion,
    DigestResourceType,
    EventDefinitionList,
    ExperimentList,
    ExternalDataSourceList,
    FeatureFlagList,
    FilterList,
    GenerateDigestDataBatchInput,
    GenerateOrganizationDigestInput,
    OrganizationDigest,
    PlaylistCount,
    RecordingCount,
    SendWeeklyDigestBatchInput,
    SurveyList,
    TeamDigest,
    UserDigestContext,
)


def _redis_url(common: CommonInput) -> str:
    return f"redis://{common.redis_host}:{common.redis_port}?decode_responses=true"


async def _load_playlist_counts_from_django_cache(r: redis.Redis, filters: FilterList) -> list[PlaylistCount | None]:
    resp: list[str | None] = await r.mget(
        [f"{PLAYLIST_COUNT_REDIS_PREFIX}{_filter.short_id}" for _filter in filters.root]
    )

    playlist_counts: list[PlaylistCount | None] = []

    for count in resp:
        if count is None:
            playlist_counts.append(None)
        else:
            try:
                playlist_counts.append(PlaylistCount.model_validate_json(count))
            except ValidationError:
                # Failure to parse means the counting job likely had an error
                # Treat it the same as a missing count
                playlist_counts.append(None)

    return playlist_counts


LOGGER = get_write_only_logger()


async def generate_digest_data_lookup(
    input: GenerateDigestDataBatchInput,
    key_kind: TeamDataKey,
    query_func: Callable[[datetime, datetime], QuerySet],
    resource_type: DigestResourceType,
) -> None:
    async with Heartbeater():
        bind_contextvars(
            digest_key=input.digest.key,
            period_start=input.digest.period_start,
            period_end=input.digest.period_end,
            batch_start=input.batch[0],
            batch_end=input.batch[1],
        )
        logger = LOGGER.bind()
        logger.info("Generating digest data batch", key_kind=key_kind)

        resource_count = 0
        team_count = 0

        async with redis.from_url(_redis_url(input.common)) as r:
            db_query: QuerySet = query_func(input.digest.period_start, input.digest.period_end)

            batch_start, batch_end = input.batch
            async for team in query_teams_for_digest()[batch_start:batch_end]:
                try:
                    digest_data = resource_type(await queryset_to_list(db_query.filter(team_id=team.id)))

                    key = team_data_key(input.digest.key, key_kind, team.id)
                    await r.setex(key, input.common.redis_ttl, digest_data.model_dump_json())

                    team_count += 1
                    resource_count += len(digest_data.root)
                except Exception as e:
                    logger.warning(
                        f"Failed to generate digest data for team {team.id}, skipping...", error=str(e), team_id=team.id
                    )
                    continue

        logger.info(
            "Finished generating digest data batch",
            key_kind=key_kind,
            resource_count=resource_count,
            team_count=team_count,
        )


@activity.defn(name="generate-dashboard-lookup")
async def generate_dashboard_lookup(input: GenerateDigestDataBatchInput) -> None:
    return await generate_digest_data_lookup(
        input,
        key_kind=TeamDataKey.DASHBOARDS,
        query_func=query_new_dashboards,
        resource_type=DashboardList,
    )


@activity.defn(name="generate-event-definition-lookup")
async def generate_event_definition_lookup(input: GenerateDigestDataBatchInput) -> None:
    return await generate_digest_data_lookup(
        input,
        key_kind=TeamDataKey.EVENT_DEFINITIONS,
        query_func=query_new_event_definitions,
        resource_type=EventDefinitionList,
    )


@activity.defn(name="generate-experiment-completed-lookup")
async def generate_experiment_completed_lookup(input: GenerateDigestDataBatchInput) -> None:
    await generate_digest_data_lookup(
        input,
        key_kind=TeamDataKey.EXPERIMENTS_COMPLETED,
        query_func=query_experiments_completed,
        resource_type=ExperimentList,
    )


@activity.defn(name="generate-experiment-launched-lookup")
async def generate_experiment_launched_lookup(input: GenerateDigestDataBatchInput) -> None:
    return await generate_digest_data_lookup(
        input,
        key_kind=TeamDataKey.EXPERIMENTS_LAUNCHED,
        query_func=query_experiments_launched,
        resource_type=ExperimentList,
    )


@activity.defn(name="generate-external-data-source-lookup")
async def generate_external_data_source_lookup(input: GenerateDigestDataBatchInput) -> None:
    return await generate_digest_data_lookup(
        input,
        key_kind=TeamDataKey.EXTERNAL_DATA_SOURCES,
        query_func=query_new_external_data_sources,
        resource_type=ExternalDataSourceList,
    )


@activity.defn(name="generate-feature-flag-lookup")
async def generate_feature_flag_lookup(input: GenerateDigestDataBatchInput) -> None:
    return await generate_digest_data_lookup(
        input,
        key_kind=TeamDataKey.FEATURE_FLAGS,
        query_func=query_new_feature_flags,
        resource_type=FeatureFlagList,
    )


@activity.defn(name="generate-survey-lookup")
async def generate_survey_lookup(input: GenerateDigestDataBatchInput) -> None:
    return await generate_digest_data_lookup(
        input,
        key_kind=TeamDataKey.SURVEYS_LAUNCHED,
        query_func=query_surveys_launched,
        resource_type=SurveyList,
    )


@activity.defn(name="generate-filter-lookup")
async def generate_filter_lookup(input: GenerateDigestDataBatchInput) -> None:
    async with Heartbeater():
        bind_contextvars(
            digest_key=input.digest.key,
            period_start=input.digest.period_start,
            period_end=input.digest.period_end,
            batch_start=input.batch[0],
            batch_end=input.batch[1],
        )
        logger = LOGGER.bind()
        logger.info(f"Generating Replay filter batch")

        filter_count = 0
        team_count = 0

        if input.common.django_redis_url is None:
            logger.error(f"Unable to generate Replay filter batch, missing URL for Django Redis...")
            return

        async with (
            redis.from_url(_redis_url(input.common)) as r,
            redis.from_url(input.common.django_redis_url) as django_cache,
        ):
            query_filters: QuerySet = query_saved_filters(input.digest.period_start, input.digest.period_end)

            batch_start, batch_end = input.batch
            async for team in query_teams_for_digest()[batch_start:batch_end]:
                try:
                    filters = FilterList(await queryset_to_list(query_filters.filter(team_id=team.id)))
                    playlist_counts = await _load_playlist_counts_from_django_cache(django_cache, filters)

                    for filter, playlist_count in zip(filters.root, playlist_counts):
                        if playlist_count is not None:
                            filter.recording_count = len(playlist_count.session_ids)
                            filter.more_available = playlist_count.has_more

                    ordered_filters = filters.order_by_recording_count()

                    key = team_data_key(input.digest.key, TeamDataKey.SAVED_FILTERS, team.id)
                    await r.setex(key, input.common.redis_ttl, ordered_filters.model_dump_json())

                    team_count += 1
                    filter_count += len(ordered_filters.root)
                except Exception as e:
                    logger.warning(
                        f"Failed to generate Replay filters for team {team.id}, skipping...",
                        error=str(e),
                        team_id=team.id,
                    )
                    continue

        logger.info(
            f"Finished generating Replay filter batch",
            filter_count=filter_count,
            team_count=team_count,
        )


TTL_THRESHOLD = 10  # days


@activity.defn(name="generate-recording-lookup")
async def generate_recording_lookup(input: GenerateDigestDataBatchInput) -> None:
    async with Heartbeater():
        bind_contextvars(
            digest_key=input.digest.key,
            period_start=input.digest.period_start,
            period_end=input.digest.period_end,
            batch_start=input.batch[0],
            batch_end=input.batch[1],
        )
        logger = LOGGER.bind()
        logger.info(f"Generating Replay recording count batch")

        recording_count = 0
        team_count = 0

        async with redis.from_url(_redis_url(input.common)) as r, get_ch_client() as ch_client:
            ch_query: str = SessionReplayEvents.count_soon_to_expire_sessions_query(format="JSON")

            batch_start, batch_end = input.batch
            async for team in query_teams_for_digest()[batch_start:batch_end]:
                try:
                    parameters = {
                        "team_id": team.id,
                        "python_now": datetime.now(UTC),
                        "ttl_threshold": TTL_THRESHOLD,
                    }

                    raw_response: bytes = b""
                    async with ch_client.aget_query(
                        query=ch_query,
                        query_parameters=parameters,
                        query_id=str(uuid4()),
                    ) as ch_response:
                        raw_response = await ch_response.content.read()

                    response = ClickHouseResponse.model_validate_json(raw_response)
                    expiring_recordings = RecordingCount.model_validate(response.data[0])

                    key = team_data_key(input.digest.key, TeamDataKey.EXPIRING_RECORDINGS, team.id)
                    await r.setex(key, input.common.redis_ttl, expiring_recordings.model_dump_json())

                    team_count += 1
                    recording_count += expiring_recordings.recording_count
                except Exception as e:
                    logger.warning(
                        f"Failed to generate Replay recording count for team {team.id}, skipping...",
                        error=str(e),
                        team_id=team.id,
                    )
                    continue

        logger.info(
            f"Finished generating Replay recording count batch",
            recording_count=recording_count,
            team_count=team_count,
        )


@activity.defn(name="generate-user-notification-lookup")
async def generate_user_notification_lookup(input: GenerateDigestDataBatchInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest.key, batch_start=input.batch[0], batch_end=input.batch[1])
        logger = LOGGER.bind()
        logger.info("Generating team access and notification settings batch")

        team_count = 0
        user_count = 0

        async with redis.from_url(_redis_url(input.common)) as r:
            batch_start, batch_end = input.batch
            async for team in query_teams_for_digest()[batch_start:batch_end]:
                try:
                    async for user in await database_sync_to_async(team.all_users_with_access)():
                        if should_send_notification(user, NotificationSetting.WEEKLY_PROJECT_DIGEST.value, team.id):
                            key = user_data_key(input.digest.key, UserDataKey.NOTIFY_TEAMS, user.id)
                            await r.sadd(key, team.id)
                            await r.expire(key, input.common.redis_ttl)

                        user_count += 1
                    team_count += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to generate access and notification settings for team {team.id}, skipping...",
                        error=str(e),
                        team_id=team.id,
                    )
                    continue

        logger.info(
            "Finished generating team access and notification settings batch",
            user_count=user_count,
            team_count=team_count,
        )


@activity.defn(name="generate-product-suggestion-lookup")
async def generate_product_suggestion_lookup(input: GenerateDigestDataBatchInput) -> None:
    async with Heartbeater():
        bind_contextvars(
            digest_key=input.digest.key,
            period_start=input.digest.period_start,
            period_end=input.digest.period_end,
            batch_start=input.batch[0],
            batch_end=input.batch[1],
        )
        logger = LOGGER.bind()
        logger.info("Generating product suggestions batch")

        team_count = 0
        user_count = 0
        suggestion_count = 0
        users_with_suggestion: set[int] = set()

        async with redis.from_url(_redis_url(input.common)) as r:
            batch_start, batch_end = input.batch
            async for team in query_teams_for_digest()[batch_start:batch_end]:
                try:
                    async for user in await database_sync_to_async(team.all_users_with_access)():
                        # Only store one suggestion per user (first one found)
                        if user.id in users_with_suggestion:
                            continue

                        suggestions = await queryset_to_list(
                            query_user_product_suggestions(
                                user.id, team.id, input.digest.period_start, input.digest.period_end
                            )
                        )

                        if suggestions:
                            suggestion = DigestProductSuggestion(team_id=team.id, **suggestions[0])
                            key = user_data_key(input.digest.key, UserDataKey.PRODUCT_SUGGESTION, user.id)
                            await r.setex(key, input.common.redis_ttl, suggestion.model_dump_json())
                            users_with_suggestion.add(user.id)
                            suggestion_count += 1

                        user_count += 1
                    team_count += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to generate product suggestions for team {team.id}, skipping...",
                        error=str(e),
                        team_id=team.id,
                    )
                    continue

        logger.info(
            "Finished generating product suggestions batch",
            user_count=user_count,
            team_count=team_count,
            suggestion_count=suggestion_count,
        )


@activity.defn(name="count-organizations")
async def count_organizations() -> int:
    async with Heartbeater():
        return await query_orgs_for_digest().acount()


@activity.defn(name="count-teams")
async def count_teams() -> int:
    async with Heartbeater():
        return await query_teams_for_digest().acount()


@activity.defn(name="generate-organization-digest-batch")
async def generate_organization_digest_batch(input: GenerateOrganizationDigestInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest.key, batch_start=input.batch[0], batch_end=input.batch[1])
        logger = LOGGER.bind()
        logger.info("Generating organization-level digest batch")

        organization_count = 0
        team_count = 0

        async with redis.from_url(_redis_url(input.common)) as r:
            batch_start, batch_end = input.batch
            async for organization in query_orgs_for_digest()[batch_start:batch_end]:
                try:
                    team_digests: list[TeamDigest] = []

                    async for team in query_org_teams(organization):
                        results: list[str | None] = await r.mget(
                            [
                                team_data_key(input.digest.key, TeamDataKey.DASHBOARDS, team.id),
                                team_data_key(input.digest.key, TeamDataKey.EVENT_DEFINITIONS, team.id),
                                team_data_key(input.digest.key, TeamDataKey.EXPERIMENTS_LAUNCHED, team.id),
                                team_data_key(input.digest.key, TeamDataKey.EXPERIMENTS_COMPLETED, team.id),
                                team_data_key(input.digest.key, TeamDataKey.EXTERNAL_DATA_SOURCES, team.id),
                                team_data_key(input.digest.key, TeamDataKey.FEATURE_FLAGS, team.id),
                                team_data_key(input.digest.key, TeamDataKey.SAVED_FILTERS, team.id),
                                team_data_key(input.digest.key, TeamDataKey.EXPIRING_RECORDINGS, team.id),
                                team_data_key(input.digest.key, TeamDataKey.SURVEYS_LAUNCHED, team.id),
                            ]
                        )

                        defaults = [
                            DashboardList(root=[]),
                            EventDefinitionList(root=[]),
                            ExperimentList(root=[]),
                            ExperimentList(root=[]),
                            ExternalDataSourceList(root=[]),
                            FeatureFlagList(root=[]),
                            FilterList(root=[]),
                            RecordingCount(recording_count=0),
                            SurveyList(root=[]),
                        ]

                        digest_data = [
                            default if result is None else default.__class__.model_validate_json(result)
                            for default, result in zip(defaults, results)
                        ]

                        team_digests.append(
                            TeamDigest(
                                id=team.id,
                                name=team.name,
                                dashboards=digest_data[0],
                                event_definitions=digest_data[1],
                                experiments_launched=digest_data[2],
                                experiments_completed=digest_data[3],
                                external_data_sources=digest_data[4],
                                feature_flags=digest_data[5],
                                filters=digest_data[6],
                                expiring_recordings=digest_data[7],
                                surveys_launched=digest_data[8],
                            )
                        )
                        team_count += 1

                    org_digest = OrganizationDigest(
                        id=organization.id,
                        name=organization.name,
                        created_at=organization.created_at,
                        team_digests=team_digests,
                    )

                    key = org_digest_key(input.digest.key, organization.id)
                    await r.setex(key, input.common.redis_ttl, org_digest.model_dump_json())

                    organization_count += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to generate organization-level digest for organization {organization.id}, skipping...",
                        error=str(e),
                        org_id=organization.id,
                    )
                    continue

        logger.info(
            "Finished generating organization-level digest batch",
            organization_count=organization_count,
            team_count=team_count,
        )


RECORD_BATCH_SIZE = 100
DIGEST_ITEM_COUNT_THRESHOLD = 4


@activity.defn(name="send-weekly-digest-batch")
async def send_weekly_digest_batch(input: SendWeeklyDigestBatchInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest.key, batch_start=input.batch[0], batch_end=input.batch[1])
        logger = LOGGER.bind()
        logger.info("Sending weekly digest batch")

        sent_digest_count = 0
        empty_org_digest_count = 0
        empty_user_digest_count = 0

        # Only US deployment forwards email events to customer.io
        ph_client: Posthog = get_ph_client(region="US", sync_mode=True)

        if not ph_client and not input.dry_run:
            logger.error("Failed to set up Posthog client")
            return

        messaging_record_batch: list[MessagingRecord] = []

        async with redis.from_url(_redis_url(input.common)) as r:
            batch_start, batch_end = input.batch
            async for organization in query_orgs_for_digest()[batch_start:batch_end]:
                partial = False
                try:
                    raw_digest: Optional[str] = await r.get(org_digest_key(input.digest.key, organization.id))

                    if not raw_digest:
                        logger.warning(
                            f"Missing digest data for organization, skipping...", organization_id=organization.id
                        )
                        continue

                    org_digest: OrganizationDigest = OrganizationDigest.model_validate_json(raw_digest)

                    if org_digest.is_empty() or org_digest.count_items() < DIGEST_ITEM_COUNT_THRESHOLD:
                        logger.warning(
                            "Got empty digest for organization, skipping...", organization_id=organization.id
                        )
                        empty_org_digest_count += 1
                        continue

                    messaging_record, created = await MessagingRecord.objects.aget_or_create(
                        email_hash=get_email_hash(f"org_{organization.id}"), campaign_key=input.digest.key
                    )

                    if not created and messaging_record.sent_at and not input.allow_already_sent:
                        logger.info(
                            f"Digest already sent for organization, skipping...", organization_id=organization.id
                        )
                        continue

                    async for member in query_org_members(organization):
                        user = member.user
                        user_notify_teams: set[int] = set(
                            map(
                                int,
                                await r.smembers(user_data_key(input.digest.key, UserDataKey.NOTIFY_TEAMS, user.id)),
                            )
                        )

                        # Load user-specific context
                        product_suggestion: DigestProductSuggestion | None = None
                        raw_suggestion: str | None = await r.get(
                            user_data_key(input.digest.key, UserDataKey.PRODUCT_SUGGESTION, user.id)
                        )
                        if raw_suggestion:
                            try:
                                product_suggestion = DigestProductSuggestion.model_validate_json(raw_suggestion)
                            except ValidationError:
                                logger.warning(
                                    "Failed to parse product suggestion, skipping...",
                                    user_id=user.id,
                                )

                        user_context = UserDigestContext(product_suggestion=product_suggestion)
                        digest_for_user = org_digest.for_user(user_notify_teams, user_context)

                        if digest_for_user.is_empty() or digest_for_user.count_items() < DIGEST_ITEM_COUNT_THRESHOLD:
                            logger.warning(
                                "Got empty digest for user, skipping...",
                                organization_id=organization.id,
                                user_id=user.id,
                            )
                            empty_user_digest_count += 1
                            continue

                        payload = digest_for_user.render_payload(input.digest)

                        if input.dry_run:
                            logger.info(
                                "DRY RUN - would send digest",
                                digest=payload,
                                user_email=user.email,
                            )
                        else:
                            partial = True
                            ph_client.capture(
                                distinct_id=user.distinct_id,
                                event="transactional email",
                                properties=payload,
                                groups={
                                    "organization": str(organization.id),
                                    "instance": settings.SITE_URL,
                                },
                            )

                        sent_digest_count += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to send weekly digest for organization {organization.id}, skipping...",
                        error=str(e),
                        organization_id=organization.id,
                    )
                    continue
                finally:
                    if not input.dry_run and partial:
                        messaging_record.sent_at = timezone.now()
                        messaging_record_batch.append(messaging_record)

                    if len(messaging_record_batch) >= RECORD_BATCH_SIZE:
                        await MessagingRecord.objects.abulk_update(messaging_record_batch, ["sent_at"])
                        messaging_record_batch = []

        if len(messaging_record_batch) > 0:
            await MessagingRecord.objects.abulk_update(messaging_record_batch, ["sent_at"])

        logger.info(
            "Finished sending weekly digest batch",
            sent_digest_count=sent_digest_count,
            empty_org_digest_count=empty_org_digest_count,
            empty_user_digest_count=empty_user_digest_count,
        )
