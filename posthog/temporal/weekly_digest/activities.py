from django.db.models import QuerySet

import redis.asyncio as redis
from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.tasks.email import NotificationSetting, should_send_notification
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.weekly_digest.queries import (
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
    SurveyList,
)

LOGGER = get_write_only_logger()


@activity.defn(name="generate-dashboard-lookup")
async def generate_dashboard_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        dashboard_query: QuerySet = query_teams_with_new_dashboards(input.period_end, input.period_start)
        async for team in query_teams_for_digest():
            dashboards = DashboardList(
                dashboards=await database_sync_to_async(list)(dashboard_query.filter(team_id=team.id))
            )
            key: str = f"weekly-digest-dashboards-{team.id}"
            await r.set(key, dashboards.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()


@activity.defn(name="generate-event-definition-lookup")
async def generate_event_definition_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        event_definition_query: QuerySet = query_teams_with_new_event_definitions(input.period_end, input.period_start)
        async for team in query_teams_for_digest():
            event_definitions = EventDefinitionList(
                definitions=await database_sync_to_async(list)(event_definition_query.filter(team_id=team.id))
            )
            key: str = f"weekly-digest-event-definitions-{team.id}"
            await r.set(key, event_definitions.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()


@activity.defn(name="generate-experiment-lookup")
async def generate_experiment_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
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
            key: str = f"weekly-digest-experiments-launched-{team.id}"
            await r.set(key, experiments_launched.model_dump_json(), ex=input.redis_ttl)

            experiments_completed = ExperimentList(
                experiments=await database_sync_to_async(list)(experiments_completed_query.filter(team_id=team.id))
            )
            key: str = f"weekly-digest-experiments-completed-{team.id}"
            await r.set(key, experiments_completed.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()


@activity.defn(name="generate-external-data-source-lookup")
async def generate_external_data_source_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        external_data_source_query: QuerySet = query_teams_with_new_external_data_sources(
            input.period_end, input.period_start
        )
        async for team in query_teams_for_digest():
            sources = ExternalDataSourceList(
                sources=await database_sync_to_async(list)(external_data_source_query.filter(team_id=team.id))
            )
            key: str = f"weekly-digest-external-data-sources-{team.id}"
            await r.set(key, sources.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()


@activity.defn(name="generate-survey-lookup")
async def generate_survey_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        survey_query: QuerySet = query_teams_with_surveys_launched(input.period_end, input.period_start)
        async for team in query_teams_for_digest():
            surveys_launched = SurveyList(
                surveys=await database_sync_to_async(list)(survey_query.filter(team_id=team.id))
            )
            key: str = f"weekly-digest-surveys-launched-{team.id}"
            await r.set(key, surveys_launched.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()


@activity.defn(name="generate-feature-flag-lookup")
async def generate_feature_flag_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        feature_flag_query: QuerySet = query_teams_with_new_feature_flags(input.period_end, input.period_start)
        async for team in query_teams_for_digest():
            flags = FeatureFlagList(
                flags=await database_sync_to_async(list)(feature_flag_query.filter(team_id=team.id))
            )
            key: str = f"weekly-digest-feature-flags-{team.id}"
            await r.set(key, flags.model_dump_json(), ex=input.redis_ttl)

        await r.aclose()


@activity.defn(name="generate-user-notification-lookup")
async def generate_user_notification_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        r = await redis.from_url(f"redis://{input.redis_host}:{input.redis_port}?decode_responses=true")

        async for team in query_teams_for_digest():
            async for user in await database_sync_to_async(team.all_users_with_access)():
                if should_send_notification(user, NotificationSetting.WEEKLY_PROJECT_DIGEST.value, team.id):
                    key: str = f"weekly-digest-user-notify-{user.id}"
                    await r.sadd(key, team.id)
                    await r.expire(key, input.redis_ttl)

        await r.aclose()
