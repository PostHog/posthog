from collections.abc import Callable
from datetime import UTC, datetime

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

import redis
from posthoganalytics import Posthog
from pydantic import ValidationError
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.schema import HogQLFilters

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.models.messaging import MessagingRecord
from posthog.models.organization_notification_lock import notification_locks_for_users
from posthog.models.team import Team
from posthog.ph_client import get_client as get_ph_client
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX
from posthog.tasks.email import NotificationSetting, should_send_notification
from posthog.tasks.email_utils import compute_week_over_week_change
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.common.utils import asyncify
from posthog.temporal.weekly_digest.keys import TeamDataKey, UserDataKey, org_digest_key, team_data_key, user_data_key
from posthog.temporal.weekly_digest.queries import (
    query_experiments_completed,
    query_experiments_launched,
    query_new_dashboards,
    query_new_error_issues,
    query_new_event_definitions,
    query_new_external_data_sources,
    query_new_feature_flags,
    query_org_members,
    query_org_product_push_campaigns,
    query_org_teams,
    query_orgs_for_digest,
    query_saved_filters,
    query_surveys_launched,
    query_team_ids_for_digest,
    query_teams_for_digest,
)
from posthog.temporal.weekly_digest.types import (
    CommonInput,
    DashboardList,
    DigestProductSuggestion,
    DigestResourceType,
    ErrorIssueList,
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
    TeamIdRange,
    UsageTrendMetric,
    UsageTrends,
    UserDigestContext,
)

from products.growth.backend.product_push.selection import project_uses_product, resolve_product_path

# Every activity below is a sync body behind `@asyncify`, which runs it on the worker's thread pool.
# Django's async ORM and `database_sync_to_async` both default to `thread_sensitive=True`, which
# funnels every database call from every concurrent activity in the process through one shared
# thread. Sync bodies on the pool give each activity its own thread and database connection, and
# keep Django's async-unsafe guard from tripping on helpers such as `should_send_notification`.

LOGGER = get_write_only_logger()


def _redis_url(common: CommonInput) -> str:
    return f"redis://{common.redis_host}:{common.redis_port}?decode_responses=true"


def _digest_redis(common: CommonInput) -> redis.Redis:
    return redis.Redis.from_url(_redis_url(common))


def _bind_batch_logger(input: GenerateDigestDataBatchInput):
    bind_contextvars(
        digest_key=input.digest.key,
        period_start=input.digest.period_start,
        period_end=input.digest.period_end,
        team_id_start=input.team_id_range.start,
        team_id_end=input.team_id_range.end,
    )
    return LOGGER.bind()


def _load_playlist_counts_from_django_cache(r: redis.Redis, filters: FilterList) -> list[PlaylistCount | None]:
    resp: list[bytes | None] = r.mget([f"{PLAYLIST_COUNT_REDIS_PREFIX}{_filter.short_id}" for _filter in filters.root])

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


def _teams_in_range(input: GenerateDigestDataBatchInput, *, with_organization: bool = False) -> QuerySet:
    # An id predicate lets Postgres seek to the first row of the batch on the primary key.
    # LIMIT/OFFSET made it build and discard every row before the batch instead.
    return query_teams_for_digest(with_organization=with_organization).filter(
        id__gte=input.team_id_range.start, id__lt=input.team_id_range.end
    )


def generate_digest_data_lookup(
    input: GenerateDigestDataBatchInput,
    key_kind: TeamDataKey,
    query_func: Callable[[datetime, datetime], QuerySet],
    resource_type: DigestResourceType,
    per_team_limit: int | None = None,
) -> None:
    logger = _bind_batch_logger(input)
    logger.info("Generating digest data batch", key_kind=key_kind)

    resource_count = 0
    team_count = 0

    with _digest_redis(input.common) as r:
        db_query: QuerySet = query_func(input.digest.period_start, input.digest.period_end)

        for team in _teams_in_range(input):
            try:
                team_query = db_query.filter(team_id=team.id)
                if per_team_limit is not None:
                    team_query = team_query[:per_team_limit]
                digest_data = resource_type(list(team_query))

                key = team_data_key(input.digest.key, key_kind, team.id)
                r.setex(key, input.common.redis_ttl, digest_data.model_dump_json())

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
@asyncify
def generate_dashboard_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        generate_digest_data_lookup(
            input,
            key_kind=TeamDataKey.DASHBOARDS,
            query_func=query_new_dashboards,
            resource_type=DashboardList,
        )


@activity.defn(name="generate-event-definition-lookup")
@asyncify
def generate_event_definition_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        generate_digest_data_lookup(
            input,
            key_kind=TeamDataKey.EVENT_DEFINITIONS,
            query_func=query_new_event_definitions,
            resource_type=EventDefinitionList,
        )


@activity.defn(name="generate-experiment-completed-lookup")
@asyncify
def generate_experiment_completed_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        generate_digest_data_lookup(
            input,
            key_kind=TeamDataKey.EXPERIMENTS_COMPLETED,
            query_func=query_experiments_completed,
            resource_type=ExperimentList,
        )


@activity.defn(name="generate-experiment-launched-lookup")
@asyncify
def generate_experiment_launched_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        generate_digest_data_lookup(
            input,
            key_kind=TeamDataKey.EXPERIMENTS_LAUNCHED,
            query_func=query_experiments_launched,
            resource_type=ExperimentList,
        )


@activity.defn(name="generate-external-data-source-lookup")
@asyncify
def generate_external_data_source_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        generate_digest_data_lookup(
            input,
            key_kind=TeamDataKey.EXTERNAL_DATA_SOURCES,
            query_func=query_new_external_data_sources,
            resource_type=ExternalDataSourceList,
        )


@activity.defn(name="generate-feature-flag-lookup")
@asyncify
def generate_feature_flag_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        generate_digest_data_lookup(
            input,
            key_kind=TeamDataKey.FEATURE_FLAGS,
            query_func=query_new_feature_flags,
            resource_type=FeatureFlagList,
        )


@activity.defn(name="generate-survey-lookup")
@asyncify
def generate_survey_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        generate_digest_data_lookup(
            input,
            key_kind=TeamDataKey.SURVEYS_LAUNCHED,
            query_func=query_surveys_launched,
            resource_type=SurveyList,
        )


def _generate_filter_lookup(input: GenerateDigestDataBatchInput) -> None:
    logger = _bind_batch_logger(input)
    logger.info("Generating Replay filter batch")

    filter_count = 0
    team_count = 0

    if input.common.django_redis_url is None:
        logger.error("Unable to generate Replay filter batch, missing URL for Django Redis...")
        return

    with (
        _digest_redis(input.common) as r,
        redis.Redis.from_url(input.common.django_redis_url) as django_cache,
    ):
        query_filters: QuerySet = query_saved_filters(input.digest.period_start, input.digest.period_end)

        for team in _teams_in_range(input):
            try:
                filters = FilterList(list(query_filters.filter(team_id=team.id)))
                playlist_counts = _load_playlist_counts_from_django_cache(django_cache, filters)

                for filter, playlist_count in zip(filters.root, playlist_counts):
                    if playlist_count is not None:
                        filter.recording_count = len(playlist_count.session_ids)
                        filter.more_available = playlist_count.has_more

                ordered_filters = filters.order_by_recording_count()

                key = team_data_key(input.digest.key, TeamDataKey.SAVED_FILTERS, team.id)
                r.setex(key, input.common.redis_ttl, ordered_filters.model_dump_json())

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
        "Finished generating Replay filter batch",
        filter_count=filter_count,
        team_count=team_count,
    )


@activity.defn(name="generate-filter-lookup")
@asyncify
def generate_filter_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        _generate_filter_lookup(input)


TTL_THRESHOLD = 10  # days


def _generate_recording_lookup(input: GenerateDigestDataBatchInput) -> None:
    logger = _bind_batch_logger(input)
    logger.info("Generating Replay recording count batch")

    recording_count = 0
    team_count = 0

    ch_query: str = SessionReplayEvents.count_soon_to_expire_sessions_query()

    with _digest_redis(input.common) as r:
        for team in _teams_in_range(input):
            try:
                rows = sync_execute(
                    ch_query,
                    {
                        "team_id": team.id,
                        "python_now": datetime.now(UTC),
                        "ttl_threshold": TTL_THRESHOLD,
                    },
                    workload=Workload.OFFLINE,
                    team_id=team.id,
                )
                expiring_recordings = RecordingCount(recording_count=int(rows[0][0]) if rows else 0)

                key = team_data_key(input.digest.key, TeamDataKey.EXPIRING_RECORDINGS, team.id)
                r.setex(key, input.common.redis_ttl, expiring_recordings.model_dump_json())

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
        "Finished generating Replay recording count batch",
        recording_count=recording_count,
        team_count=team_count,
    )


@activity.defn(name="generate-recording-lookup")
@asyncify
def generate_recording_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        _generate_recording_lookup(input)


# Issue names come from exception ingestion, so a noisy (or malicious) client can create
# hundreds of new issues in a week. Cap at the 5 newest per team, mirroring the error
# tracking weekly digest, which also shows at most 5 new issues.
NEW_ERROR_ISSUES_PER_TEAM_LIMIT = 5


@activity.defn(name="generate-error-issue-lookup")
@asyncify
def generate_error_issue_lookup(input: GenerateDigestDataBatchInput) -> None:
    # New error-tracking issues follow the standard "created within window" lookup,
    # exactly like dashboards / feature flags.
    with HeartbeaterSync(logger=LOGGER):
        generate_digest_data_lookup(
            input,
            key_kind=TeamDataKey.ERROR_ISSUES,
            query_func=query_new_error_issues,
            resource_type=ErrorIssueList,
            per_team_limit=NEW_ERROR_ISSUES_PER_TEAM_LIMIT,
        )


# Weekly usage snapshot per team. Written in HogQL so it inherits the team's test-account
# filtering (the numbers match what the team sees in product analytics) and column translation.
# "Active users" mirrors the DAU/WAU trends definition — distinct persons, `uniqExactIf(person_id)`,
# which is the conditional form of the `count(DISTINCT person_id)` those insights print. Counting
# distinct_ids would overcount (one person, many devices). Two windows are compared in one pass;
# the query runs on the offline cluster since it scans two weeks of events for every active team.
USAGE_TRENDS_QUERY = """
SELECT
    countIf(timestamp >= {cur_start} AND timestamp < {cur_end}) AS events_current,
    countIf(timestamp >= {prev_start} AND timestamp < {cur_start}) AS events_previous,
    uniqExactIf(person_id, timestamp >= {cur_start} AND timestamp < {cur_end}) AS users_current,
    uniqExactIf(person_id, timestamp >= {prev_start} AND timestamp < {cur_start}) AS users_previous
FROM events
WHERE timestamp >= {prev_start} AND timestamp < {cur_end} AND {filters}
"""


def _usage_trend_metric(label: str, current: int, previous: int) -> UsageTrendMetric:
    has_baseline = previous > 0
    change = compute_week_over_week_change(current, previous if has_baseline else None, higher_is_better=True)
    if change is None:
        return UsageTrendMetric(label=label, current=current, previous=previous, has_baseline=has_baseline)
    return UsageTrendMetric(
        label=label,
        current=current,
        previous=previous,
        change_pct=change["percent"],
        direction="up" if change["direction"] == "Up" else "down",
        has_baseline=True,
    )


def _query_team_usage_trends(team_id: int, period_start: datetime, period_end: datetime) -> UsageTrends | None:
    """Run the per-team usage snapshot on the offline cluster. Returns None for inactive teams."""
    team = Team.objects.get(pk=team_id)
    window = period_end - period_start
    response = execute_hogql_query(
        query=USAGE_TRENDS_QUERY,
        team=team,
        placeholders={
            "cur_start": ast.Constant(value=period_start),
            "cur_end": ast.Constant(value=period_end),
            "prev_start": ast.Constant(value=period_start - window),
        },
        filters=HogQLFilters(filterTestAccounts=True),
        workload=Workload.OFFLINE,
    )

    if not response.results or not response.results[0]:
        return None

    events_current, events_previous, users_current, users_previous = response.results[0]
    events_current = int(events_current or 0)
    users_current = int(users_current or 0)

    # Skip inactive teams entirely — no numbers worth showing.
    if events_current == 0:
        return None

    return UsageTrends(
        metrics=[
            _usage_trend_metric("Events", events_current, int(events_previous or 0)),
            _usage_trend_metric("Active users", users_current, int(users_previous or 0)),
        ]
    )


def _generate_usage_trends_lookup(input: GenerateDigestDataBatchInput) -> None:
    logger = _bind_batch_logger(input)
    logger.info("Generating usage trends batch")

    team_count = 0
    attempted = 0
    error_count = 0

    with _digest_redis(input.common) as r:
        for team in _teams_in_range(input):
            attempted += 1
            try:
                usage_trends = _query_team_usage_trends(team.id, input.digest.period_start, input.digest.period_end)
            except Exception as e:
                error_count += 1
                logger.warning(
                    f"Failed to generate usage trends for team {team.id}, skipping...",
                    error=str(e),
                    team_id=team.id,
                )
                continue

            if usage_trends is None:
                continue

            key = team_data_key(input.digest.key, TeamDataKey.USAGE_TRENDS, team.id)
            r.setex(key, input.common.redis_ttl, usage_trends.model_dump_json())
            team_count += 1

    # A malformed query (or an offline-cluster outage) fails for every team, which would
    # otherwise look identical to "no active teams" and silently ship an empty section for
    # the whole batch. Surface it so the activity retries and then fails the run loudly.
    if attempted > 0 and error_count == attempted:
        raise RuntimeError(f"Usage trends query failed for all {attempted} teams in batch")

    logger.info("Finished generating usage trends batch", team_count=team_count, error_count=error_count)


@activity.defn(name="generate-usage-trends-lookup")
@asyncify
def generate_usage_trends_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        _generate_usage_trends_lookup(input)


def _generate_user_notification_lookup(input: GenerateDigestDataBatchInput) -> None:
    bind_contextvars(
        digest_key=input.digest.key, team_id_start=input.team_id_range.start, team_id_end=input.team_id_range.end
    )
    logger = LOGGER.bind()
    logger.info("Generating team access and notification settings batch")

    team_count = 0
    user_count = 0

    with _digest_redis(input.common) as r:
        for team in _teams_in_range(input, with_organization=True):
            try:
                users = list(team.all_users_with_access())
                # One lookup for the whole team instead of one per user inside should_send_notification.
                locks_by_user = notification_locks_for_users(
                    [user.id for user in users], organization_id=team.organization_id
                )
                for user in users:
                    if should_send_notification(
                        user,
                        NotificationSetting.WEEKLY_PROJECT_DIGEST.value,
                        team.id,
                        locks=locks_by_user.get(user.id, {}),
                    ):
                        key = user_data_key(input.digest.key, UserDataKey.NOTIFY_TEAMS, user.id)
                        r.sadd(key, team.id)
                        r.expire(key, input.common.redis_ttl)

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


@activity.defn(name="generate-user-notification-lookup")
@asyncify
def generate_user_notification_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        _generate_user_notification_lookup(input)


def _generate_product_suggestion_lookup(input: GenerateDigestDataBatchInput) -> None:
    logger = _bind_batch_logger(input)
    logger.info("Generating product suggestions batch")

    team_count = 0
    user_count = 0
    suggestion_count = 0
    users_with_suggestion: set[int] = set()
    # Campaigns are org-scoped but this batch walks teams, so cache per org.
    campaigns_by_org: dict[str, list[dict]] = {}

    with _digest_redis(input.common) as r:
        for team in _teams_in_range(input, with_organization=True):
            try:
                organization_id = str(team.organization_id)
                if organization_id not in campaigns_by_org:
                    campaigns_by_org[organization_id] = list(
                        query_org_product_push_campaigns(organization_id, input.digest.period_end)
                    )
                campaigns = campaigns_by_org[organization_id]
                if not campaigns:
                    team_count += 1
                    continue

                campaign = campaigns[0]
                product_path = resolve_product_path(campaign["product_key"])
                # The push is org-wide, but a project that already uses the product
                # shouldn't be nudged about it - same rule the nav card applies.
                if product_path is None or project_uses_product(
                    team.project_id, campaign["product_key"], organization_id
                ):
                    team_count += 1
                    continue

                for user in team.all_users_with_access():
                    # Only store one suggestion per user (first one found)
                    if user.id in users_with_suggestion:
                        continue

                    user_count += 1

                    if user.allow_sidebar_suggestions is False:
                        continue

                    suggestion = DigestProductSuggestion(
                        team_id=team.id,
                        product_path=product_path,
                        reason_text=campaign["reason_text"],
                    )
                    key = user_data_key(input.digest.key, UserDataKey.PRODUCT_SUGGESTION, user.id)
                    r.setex(key, input.common.redis_ttl, suggestion.model_dump_json())
                    users_with_suggestion.add(user.id)
                    suggestion_count += 1
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


@activity.defn(name="generate-product-suggestion-lookup")
@asyncify
def generate_product_suggestion_lookup(input: GenerateDigestDataBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        _generate_product_suggestion_lookup(input)


@activity.defn(name="count-organizations")
@asyncify
def count_organizations() -> int:
    with HeartbeaterSync(logger=LOGGER):
        return query_orgs_for_digest().count()


def _cut_team_id_ranges(team_ids: list[int], batch_size: int) -> list[TeamIdRange]:
    """Cut ordered team ids into [start, end) ranges of at most `batch_size` teams each."""
    return [
        TeamIdRange(
            start=team_ids[start],
            end=team_ids[start + batch_size] if start + batch_size < len(team_ids) else team_ids[-1] + 1,
        )
        for start in range(0, len(team_ids), batch_size)
    ]


@activity.defn(name="list-team-id-ranges")
@asyncify
def list_team_id_ranges(input: CommonInput) -> list[TeamIdRange]:
    """One index scan of the team ids replaces a LIMIT/OFFSET scan per batch per generator."""
    with HeartbeaterSync(logger=LOGGER):
        return _cut_team_id_ranges(list(query_team_ids_for_digest()), input.batch_size)


def _generate_organization_digest_batch(input: GenerateOrganizationDigestInput) -> None:
    bind_contextvars(digest_key=input.digest.key, batch_start=input.batch[0], batch_end=input.batch[1])
    logger = LOGGER.bind()
    logger.info("Generating organization-level digest batch")

    organization_count = 0
    team_count = 0

    with _digest_redis(input.common) as r:
        batch_start, batch_end = input.batch
        for organization in query_orgs_for_digest()[batch_start:batch_end]:
            try:
                team_digests: list[TeamDigest] = []

                for team in query_org_teams(organization):
                    results: list[str | None] = r.mget(
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
                            team_data_key(input.digest.key, TeamDataKey.USAGE_TRENDS, team.id),
                            team_data_key(input.digest.key, TeamDataKey.ERROR_ISSUES, team.id),
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
                        UsageTrends(),
                        ErrorIssueList(root=[]),
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
                            usage_trends=digest_data[9],
                            error_issues=digest_data[10],
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
                r.setex(key, input.common.redis_ttl, org_digest.model_dump_json())

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


@activity.defn(name="generate-organization-digest-batch")
@asyncify
def generate_organization_digest_batch(input: GenerateOrganizationDigestInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        _generate_organization_digest_batch(input)


RECORD_BATCH_SIZE = 100
DIGEST_ITEM_COUNT_THRESHOLD = 4


def _send_weekly_digest_batch(input: SendWeeklyDigestBatchInput) -> None:
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

    with _digest_redis(input.common) as r:
        batch_start, batch_end = input.batch
        for organization in query_orgs_for_digest()[batch_start:batch_end]:
            partial = False
            try:
                raw_digest: str | None = r.get(org_digest_key(input.digest.key, organization.id))

                if not raw_digest:
                    logger.warning("Missing digest data for organization, skipping...", organization_id=organization.id)
                    continue

                org_digest: OrganizationDigest = OrganizationDigest.model_validate_json(raw_digest)

                if org_digest.is_empty() or org_digest.count_items() < DIGEST_ITEM_COUNT_THRESHOLD:
                    logger.warning("Got empty digest for organization, skipping...", organization_id=organization.id)
                    empty_org_digest_count += 1
                    continue

                messaging_record, created = MessagingRecord.objects.get_or_create(
                    raw_email=f"org_{organization.id}", campaign_key=input.digest.key
                )

                if not created and messaging_record.sent_at and not input.allow_already_sent:
                    logger.info("Digest already sent for organization, skipping...", organization_id=organization.id)
                    continue

                for member in query_org_members(organization):
                    user = member.user
                    user_notify_teams: set[int] = set(
                        map(int, r.smembers(user_data_key(input.digest.key, UserDataKey.NOTIFY_TEAMS, user.id)))
                    )

                    # Load user-specific context
                    product_suggestion: DigestProductSuggestion | None = None
                    raw_suggestion: str | None = r.get(
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
                    MessagingRecord.objects.bulk_update(messaging_record_batch, ["sent_at"])
                    messaging_record_batch = []

    if len(messaging_record_batch) > 0:
        MessagingRecord.objects.bulk_update(messaging_record_batch, ["sent_at"])

    logger.info(
        "Finished sending weekly digest batch",
        sent_digest_count=sent_digest_count,
        empty_org_digest_count=empty_org_digest_count,
        empty_user_digest_count=empty_user_digest_count,
    )


@activity.defn(name="send-weekly-digest-batch")
@asyncify
def send_weekly_digest_batch(input: SendWeeklyDigestBatchInput) -> None:
    with HeartbeaterSync(logger=LOGGER):
        _send_weekly_digest_batch(input)
