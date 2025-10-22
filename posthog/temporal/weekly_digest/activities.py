import asyncio
from typing import Optional

from django.db.models import QuerySet

import redis.asyncio as redis
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.tasks.email import NotificationSetting, should_send_notification
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.weekly_digest.queries import (
    query_org_members,
    query_org_teams,
    query_orgs_for_digest,
    query_teams_for_digest,
    query_teams_with_experiments_completed,
    query_teams_with_experiments_launched,
    query_teams_with_new_dashboards,
    query_teams_with_new_event_definitions,
    query_teams_with_new_external_data_sources,
    query_teams_with_new_feature_flags,
    query_teams_with_surveys_launched,
)
from posthog.temporal.weekly_digest.types import (
    DashboardList,
    EventDefinitionList,
    ExperimentList,
    ExternalDataSourceList,
    FeatureFlagList,
    GenerateDigestDataInput,
    GenerateOrganizationDigestInput,
    OrganizationDigest,
    SendWeeklyDigestBatchInput,
    SurveyList,
    TeamDigest,
)

LOGGER = get_write_only_logger()


@activity.defn(name="generate-dashboard-lookup")
async def generate_dashboard_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest_key, period_start=input.period_start, period_end=input.period_end)
        logger = LOGGER.bind()
        logger.info("Querying new dashboards")

        dashboard_count = 0
        team_count = 0

        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        dashboard_query: QuerySet = query_teams_with_new_dashboards(input.period_end, input.period_start)
        async for team in query_teams_for_digest():
            dashboards = DashboardList(
                dashboards=await database_sync_to_async(list)(dashboard_query.filter(team_id=team.id))
            )

            dashboard_count += len(dashboards.dashboards)
            team_count += 1

            key: str = f"{input.digest_key}-dashboards-{team.id}"
            await r.set(key, dashboards.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()

        logger.info(f"Finished querying new dashboards", dashboard_count=dashboard_count, team_count=team_count)


@activity.defn(name="generate-event-definition-lookup")
async def generate_event_definition_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest_key, period_start=input.period_start, period_end=input.period_end)
        logger = LOGGER.bind()
        logger.info("Querying new event definitions")

        definition_count = 0
        team_count = 0

        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        event_definition_query: QuerySet = query_teams_with_new_event_definitions(input.period_end, input.period_start)
        async for team in query_teams_for_digest():
            event_definitions = EventDefinitionList(
                definitions=await database_sync_to_async(list)(event_definition_query.filter(team_id=team.id))
            )

            definition_count += len(event_definitions.definitions)
            team_count += 1

            key: str = f"{input.digest_key}-event-definitions-{team.id}"
            await r.set(key, event_definitions.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()

        logger.info(
            f"Finished querying new event definitions", definition_count=definition_count, team_count=team_count
        )


@activity.defn(name="generate-experiment-lookup")
async def generate_experiment_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest_key, period_start=input.period_start, period_end=input.period_end)
        logger = LOGGER.bind()
        logger.info("Querying experiments launched and completed")

        experiments_launched_count = 0
        experiments_completed_count = 0
        team_count = 0

        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        experiments_launched_query: QuerySet = query_teams_with_experiments_launched(
            input.period_end, input.period_start
        )
        experiments_completed_query: QuerySet = query_teams_with_experiments_completed(
            input.period_end, input.period_start
        )
        async for team in query_teams_for_digest():
            experiments_launched = ExperimentList(
                experiments=await database_sync_to_async(list)(experiments_launched_query.filter(team_id=team.id))
            )

            experiments_launched_count += len(experiments_launched.experiments)

            key: str = f"{input.digest_key}-experiments-launched-{team.id}"
            await r.set(key, experiments_launched.model_dump_json(), ex=input.redis_ttl)

            experiments_completed = ExperimentList(
                experiments=await database_sync_to_async(list)(experiments_completed_query.filter(team_id=team.id))
            )

            experiments_completed_count += len(experiments_completed.experiments)
            team_count += 1

            key = f"{input.digest_key}-experiments-completed-{team.id}"
            await r.set(key, experiments_completed.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()

        logger.info(
            f"Finished querying new experiments",
            experiments_launched_count=experiments_launched_count,
            experiments_completed_count=experiments_completed_count,
            team_count=team_count,
        )


@activity.defn(name="generate-external-data-source-lookup")
async def generate_external_data_source_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest_key, period_start=input.period_start, period_end=input.period_end)
        logger = LOGGER.bind()
        logger.info("Querying new external data sources")

        source_count = 0
        team_count = 0

        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        external_data_source_query: QuerySet = query_teams_with_new_external_data_sources(
            input.period_end, input.period_start
        )
        async for team in query_teams_for_digest():
            sources = ExternalDataSourceList(
                sources=await database_sync_to_async(list)(external_data_source_query.filter(team_id=team.id))
            )

            source_count += len(sources.sources)
            team_count += 1

            key: str = f"{input.digest_key}-external-data-sources-{team.id}"
            await r.set(key, sources.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()

        logger.info(f"Finished querying new external data sources", source_count=source_count, team_count=team_count)


@activity.defn(name="generate-survey-lookup")
async def generate_survey_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest_key, period_start=input.period_start, period_end=input.period_end)
        logger = LOGGER.bind()
        logger.info("Querying surveys launched")

        survey_count = 0
        team_count = 0

        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        survey_query: QuerySet = query_teams_with_surveys_launched(input.period_end, input.period_start)
        async for team in query_teams_for_digest():
            surveys_launched = SurveyList(
                surveys=await database_sync_to_async(list)(survey_query.filter(team_id=team.id))
            )

            survey_count += len(surveys_launched.surveys)
            team_count += 1

            key: str = f"{input.digest_key}-surveys-launched-{team.id}"
            await r.set(key, surveys_launched.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()

        logger.info(f"Finished querying surveys launched", survey_count=survey_count, team_count=team_count)


@activity.defn(name="generate-feature-flag-lookup")
async def generate_feature_flag_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest_key, period_start=input.period_start, period_end=input.period_end)
        logger = LOGGER.bind()
        logger.info("Querying new feature flags")

        flag_count = 0
        team_count = 0

        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        feature_flag_query: QuerySet = query_teams_with_new_feature_flags(input.period_end, input.period_start)
        async for team in query_teams_for_digest():
            flags = FeatureFlagList(
                flags=await database_sync_to_async(list)(feature_flag_query.filter(team_id=team.id))
            )

            flag_count += len(flags.flags)
            team_count += 1

            key: str = f"{input.digest_key}-feature-flags-{team.id}"
            await r.set(key, flags.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()

        logger.info(f"Finished querying new feature flags", flag_count=flag_count, team_count=team_count)


@activity.defn(name="generate-user-notification-lookup")
async def generate_user_notification_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest_key)
        logger = LOGGER.bind()
        logger.info("Querying team access and notification settings")

        team_count = 0
        user_count = 0

        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        async for team in query_teams_for_digest():
            team_count += 1
            async for user in await database_sync_to_async(team.all_users_with_access)():
                user_count += 1
                if should_send_notification(user, NotificationSetting.WEEKLY_PROJECT_DIGEST.value, team.id):
                    key: str = f"{input.digest_key}-user-notify-{user.id}"
                    await r.sadd(key, team.id)
                    await r.expire(key, input.redis_ttl)

        await r.aclose()

        logger.info(
            "Finished querying team access and notification settings", user_count=user_count, team_count=team_count
        )


@activity.defn(name="count-organizations")
async def count_organizations() -> int:
    async with Heartbeater():
        return await query_orgs_for_digest().acount()


@activity.defn(name="generate-organization-digest-batch")
async def generate_organization_digest_batch(input: GenerateOrganizationDigestInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest_key, batch_start=input.batch[0], batch_end=input.batch[1])
        logger = LOGGER.bind()
        logger.info("Generating organization-level digest batch")

        organization_count = 0
        team_count = 0

        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        batch_start, batch_end = input.batch
        async for organization in query_orgs_for_digest()[batch_start:batch_end]:
            organization_count += 1

            team_digests: list[TeamDigest] = []

            async for team in query_org_teams(organization):
                team_count += 1

                digest_data: list[str] = await asyncio.gather(
                    *[
                        r.get(f"{input.digest_key}-dashboards-{team.id}"),
                        r.get(f"{input.digest_key}-event-definitions-{team.id}"),
                        r.get(f"{input.digest_key}-experiments-launched-{team.id}"),
                        r.get(f"{input.digest_key}-experiments-completed-{team.id}"),
                        r.get(f"{input.digest_key}-external-data-sources-{team.id}"),
                        r.get(f"{input.digest_key}-surveys-launched-{team.id}"),
                        r.get(f"{input.digest_key}-feature-flags-{team.id}"),
                    ]
                )

                team_digests.append(
                    TeamDigest(
                        id=team.id,
                        name=team.name,
                        dashboards=DashboardList.model_validate_json(digest_data[0]),
                        event_definitions=EventDefinitionList.model_validate_json(digest_data[1]),
                        experiments_launched=ExperimentList.model_validate_json(digest_data[2]),
                        experiments_completed=ExperimentList.model_validate_json(digest_data[3]),
                        external_data_sources=ExternalDataSourceList.model_validate_json(digest_data[4]),
                        surveys_launched=SurveyList.model_validate_json(digest_data[5]),
                        feature_flags=FeatureFlagList.model_validate_json(digest_data[6]),
                    )
                )

            org_digest = OrganizationDigest(
                id=organization.id,
                name=organization.name,
                created_at=organization.created_at,
                team_digests=team_digests,
            )

            key: str = f"{input.digest_key}-{organization.id}"
            await r.set(key, org_digest.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()

        logger.info(
            "Finished generating organization-level digests",
            organization_count=organization_count,
            team_count=team_count,
        )


@activity.defn(name="send-weekly-digest-batch")
async def send_weekly_digest_batch(input: SendWeeklyDigestBatchInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest_key, batch_start=input.batch[0], batch_end=input.batch[1])
        logger = LOGGER.bind()
        logger.info("Sending weekly digest batch")

        sent_digest_count = 0
        empty_org_digest_count = 0
        empty_user_digest_count = 0

        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        batch_start, batch_end = input.batch
        async for organization in query_orgs_for_digest()[batch_start:batch_end]:
            raw_digest: Optional[str] = await r.get(f"{input.digest_key}-{organization.id}")

            if not raw_digest:
                logger.warning(f"Missing digest data for organization", organization_id=organization.id)
                continue

            org_digest = OrganizationDigest.model_validate_json(raw_digest)

            if org_digest.is_empty():
                empty_org_digest_count += 1
                continue

            async for member in query_org_members(organization):
                user = member.user
                user_notify_teams: set[int] = set(
                    map(int, await r.smembers(f"{input.digest_key}-user-notify-{user.id}"))
                )
                user_specific_digest: OrganizationDigest = org_digest.filter_for_user(user_notify_teams)

                if user_specific_digest.is_empty():
                    empty_user_digest_count += 1
                    continue

                if input.dry_run:
                    logger.info("DRY RUN - would send digest", digest=user_specific_digest.model_dump())
                else:
                    raise NotImplementedError()

                sent_digest_count += 1

        logger.info(
            "Finished sending weekly digest batch",
            sent_digest_count=sent_digest_count,
            empty_org_digest_count=empty_org_digest_count,
            empty_user_digest_count=empty_user_digest_count,
        )
