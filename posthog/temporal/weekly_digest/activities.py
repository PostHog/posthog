import asyncio
from collections.abc import Callable
from datetime import datetime
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
    query_experiments_completed,
    query_experiments_launched,
    query_new_dashboards,
    query_new_event_definitions,
    query_new_external_data_sources,
    query_new_feature_flags,
    query_org_members,
    query_org_teams,
    query_orgs_for_digest,
    query_surveys_launched,
    query_teams_for_digest,
    queryset_to_list,
)
from posthog.temporal.weekly_digest.types import (
    CommonInput,
    DashboardList,
    DigestResourceType,
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


def _redis_url(common: CommonInput) -> str:
    return f"redis://{common.redis_host}:{common.redis_port}?decode_responses=true"


LOGGER = get_write_only_logger()


async def generate_digest_data_lookup(
    input: GenerateDigestDataInput,
    resource_key: str,
    query_func: Callable[[datetime, datetime], QuerySet],
    resource_type: DigestResourceType,
) -> None:
    async with Heartbeater():
        bind_contextvars(
            digest_key=input.digest.key, period_start=input.digest.period_start, period_end=input.digest.period_end
        )
        logger = LOGGER.bind()
        logger.info(f"Querying digest data", resource_key=resource_key)

        resource_count = 0
        team_count = 0

        async with redis.from_url(_redis_url(input.common)) as r:
            db_query: QuerySet = query_func(input.digest.period_start, input.digest.period_end)
            async for team in query_teams_for_digest():
                digest_data = resource_type(await queryset_to_list(db_query.filter(team_id=team.id)))

                resource_count += len(digest_data.root)
                team_count += 1

                key: str = f"{input.digest.key}-{resource_key}-{team.id}"
                await r.setex(key, input.common.redis_ttl, digest_data.model_dump_json())

        logger.info(
            f"Finished querying digest data",
            resource_key=resource_key,
            resource_count=resource_count,
            team_count=team_count,
        )


@activity.defn(name="generate-dashboard-lookup")
async def generate_dashboard_lookup(input: GenerateDigestDataInput) -> None:
    return await generate_digest_data_lookup(
        input,
        resource_key="dashboards",
        query_func=query_new_dashboards,
        resource_type=DashboardList,
    )


@activity.defn(name="generate-event-definition-lookup")
async def generate_event_definition_lookup(input: GenerateDigestDataInput) -> None:
    return await generate_digest_data_lookup(
        input,
        resource_key="event-definitions",
        query_func=query_new_event_definitions,
        resource_type=EventDefinitionList,
    )


@activity.defn(name="generate-experiment-completed-lookup")
async def generate_experiment_completed_lookup(input: GenerateDigestDataInput) -> None:
    await generate_digest_data_lookup(
        input,
        resource_key="experiments-completed",
        query_func=query_experiments_completed,
        resource_type=ExperimentList,
    )


@activity.defn(name="generate-experiment-launched-lookup")
async def generate_experiment_launched_lookup(input: GenerateDigestDataInput) -> None:
    return await generate_digest_data_lookup(
        input,
        resource_key="experiments-launched",
        query_func=query_experiments_launched,
        resource_type=ExperimentList,
    )


@activity.defn(name="generate-external-data-source-lookup")
async def generate_external_data_source_lookup(input: GenerateDigestDataInput) -> None:
    return await generate_digest_data_lookup(
        input,
        resource_key="external-data-sources",
        query_func=query_new_external_data_sources,
        resource_type=ExternalDataSourceList,
    )


@activity.defn(name="generate-feature-flag-lookup")
async def generate_feature_flag_lookup(input: GenerateDigestDataInput) -> None:
    return await generate_digest_data_lookup(
        input,
        resource_key="feature-flags",
        query_func=query_new_feature_flags,
        resource_type=FeatureFlagList,
    )


@activity.defn(name="generate-survey-lookup")
async def generate_survey_lookup(input: GenerateDigestDataInput) -> None:
    return await generate_digest_data_lookup(
        input,
        resource_key="surveys-launched",
        query_func=query_surveys_launched,
        resource_type=SurveyList,
    )


@activity.defn(name="generate-user-notification-lookup")
async def generate_user_notification_lookup(input: GenerateDigestDataInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest.key)
        logger = LOGGER.bind()
        logger.info("Querying team access and notification settings")

        team_count = 0
        user_count = 0

        async with redis.from_url(_redis_url(input.common)) as r:
            async for team in query_teams_for_digest():
                team_count += 1
                async for user in await database_sync_to_async(team.all_users_with_access)():
                    user_count += 1
                    if should_send_notification(user, NotificationSetting.WEEKLY_PROJECT_DIGEST.value, team.id):
                        key: str = f"{input.digest.key}-user-notify-{user.id}"
                        await r.sadd(key, team.id)
                        await r.expire(key, input.common.redis_ttl)

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
        bind_contextvars(digest_key=input.digest.key, batch_start=input.batch[0], batch_end=input.batch[1])
        logger = LOGGER.bind()
        logger.info("Generating organization-level digest batch")

        organization_count = 0
        team_count = 0

        async with redis.from_url(_redis_url(input.common)) as r:
            batch_start, batch_end = input.batch
            async for organization in query_orgs_for_digest()[batch_start:batch_end]:
                organization_count += 1

                team_digests: list[TeamDigest] = []

                async for team in query_org_teams(organization):
                    results: list[str | None] = await asyncio.gather(
                        *[
                            r.get(f"{input.digest.key}-dashboards-{team.id}"),
                            r.get(f"{input.digest.key}-event-definitions-{team.id}"),
                            r.get(f"{input.digest.key}-experiments-launched-{team.id}"),
                            r.get(f"{input.digest.key}-experiments-completed-{team.id}"),
                            r.get(f"{input.digest.key}-external-data-sources-{team.id}"),
                            r.get(f"{input.digest.key}-surveys-launched-{team.id}"),
                            r.get(f"{input.digest.key}-feature-flags-{team.id}"),
                        ]
                    )

                    digest_data: list[str] = [r for r in results if r is not None]

                    if len(digest_data) < len(results):
                        logger.warning(f"Missing digest data for team, skipping...", team_id=team.id)
                        continue

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
                    team_count += 1

                org_digest = OrganizationDigest(
                    id=organization.id,
                    name=organization.name,
                    created_at=organization.created_at,
                    team_digests=team_digests,
                )

                key: str = f"{input.digest.key}-{organization.id}"
                await r.setex(key, input.common.redis_ttl, org_digest.model_dump_json())

        logger.info(
            "Finished generating organization-level digests",
            organization_count=organization_count,
            team_count=team_count,
        )


@activity.defn(name="send-weekly-digest-batch")
async def send_weekly_digest_batch(input: SendWeeklyDigestBatchInput) -> None:
    async with Heartbeater():
        bind_contextvars(digest_key=input.digest.key, batch_start=input.batch[0], batch_end=input.batch[1])
        logger = LOGGER.bind()
        logger.info("Sending weekly digest batch")

        sent_digest_count = 0
        empty_org_digest_count = 0
        empty_user_digest_count = 0

        async with redis.from_url(_redis_url(input.common)) as r:
            batch_start, batch_end = input.batch
            async for organization in query_orgs_for_digest()[batch_start:batch_end]:
                raw_digest: Optional[str] = await r.get(f"{input.digest.key}-{organization.id}")

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
                        map(int, await r.smembers(f"{input.digest.key}-user-notify-{user.id}"))
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
