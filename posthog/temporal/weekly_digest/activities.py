import json
import math
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import UUID

from django.conf import settings
from django.db.models import F, QuerySet, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

import redis
from posthoganalytics import Posthog
from posthoganalytics.consumer import MAX_MSG_SIZE
from pydantic import ValidationError
from structlog.contextvars import bind_contextvars
from structlog.typing import FilteringBoundLogger
from temporalio import activity

from posthog.schema import HogQLFilters

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.constants import AvailableFeature
from posthog.models.messaging import MessagingRecord
from posthog.models.organization_notification_lock import GovernedSetting, notification_locks_for_users
from posthog.models.team import Team
from posthog.models.user import User
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
    query_orgs_for_digest,
    query_product_push_campaigns_for_organizations,
    query_saved_filters,
    query_surveys_launched,
    query_team_ids_for_digest,
    query_teams_for_digest,
    query_teams_for_organizations,
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

# Bounds the size of one Redis request when a batch reads or writes keys for thousands of teams.
REDIS_COMMAND_CHUNK_SIZE = 5000

T = TypeVar("T")


def _redis_url(common: CommonInput) -> str:
    return f"redis://{common.redis_host}:{common.redis_port}?decode_responses=true"


def _digest_redis(common: CommonInput) -> redis.Redis:
    return redis.Redis.from_url(_redis_url(common))


def _chunked(items: Sequence[T], size: int) -> Iterable[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _mget_chunked(r: redis.Redis, keys: Sequence[str]) -> list[Any]:
    values: list[Any] = []
    for chunk in _chunked(keys, REDIS_COMMAND_CHUNK_SIZE):
        values.extend(r.mget(list(chunk)))
    return values


def _setex_many(r: redis.Redis, ttl: int, items: Sequence[tuple[str, str]]) -> None:
    for chunk in _chunked(items, REDIS_COMMAND_CHUNK_SIZE):
        with r.pipeline(transaction=False) as pipe:
            for key, value in chunk:
                pipe.setex(key, ttl, value)
            pipe.execute()


def _delete_many(r: redis.Redis, keys: Sequence[str]) -> None:
    for chunk in _chunked(keys, REDIS_COMMAND_CHUNK_SIZE):
        r.delete(*chunk)


def _store_team_data(
    r: redis.Redis,
    input: GenerateDigestDataBatchInput,
    key_kind: TeamDataKey,
    payload_by_team: dict[int, str],
    eligible_team_ids: set[int],
) -> None:
    """Write one key per team with data and drop the key of every other eligible team.

    A retry of the same digest may find that a team's rows disappeared since the first attempt,
    so a key left over from that attempt would otherwise survive for the whole TTL.
    """
    _setex_many(
        r,
        input.common.redis_ttl,
        [(team_data_key(input.digest.key, key_kind, team_id), payload) for team_id, payload in payload_by_team.items()],
    )
    _delete_many(
        r,
        [team_data_key(input.digest.key, key_kind, team_id) for team_id in eligible_team_ids - payload_by_team.keys()],
    )


def _bind_batch_logger(input: GenerateDigestDataBatchInput) -> FilteringBoundLogger:
    bind_contextvars(
        digest_key=input.digest.key,
        period_start=input.digest.period_start,
        period_end=input.digest.period_end,
        team_id_start=input.team_id_range.start,
        team_id_end=input.team_id_range.end,
    )
    return LOGGER.bind()


def _load_playlist_counts_from_django_cache(r: redis.Redis, short_ids: Sequence[str]) -> dict[str, PlaylistCount]:
    resp: list[bytes | None] = _mget_chunked(r, [f"{PLAYLIST_COUNT_REDIS_PREFIX}{short_id}" for short_id in short_ids])

    playlist_counts: dict[str, PlaylistCount] = {}

    for short_id, count in zip(short_ids, resp):
        if count is None:
            continue
        try:
            playlist_counts[short_id] = PlaylistCount.model_validate_json(count)
        except ValidationError:
            # Failure to parse means the counting job likely had an error
            # Treat it the same as a missing count
            continue

    return playlist_counts


def _teams_in_range(input: GenerateDigestDataBatchInput, *, with_organization: bool = False) -> QuerySet:
    # An id predicate lets Postgres seek to the first row of the batch on the primary key.
    # LIMIT/OFFSET made it build and discard every row before the batch instead.
    return query_teams_for_digest(with_organization=with_organization).filter(
        id__gte=input.team_id_range.start, id__lt=input.team_id_range.end
    )


def _rows_in_range(input: GenerateDigestDataBatchInput, rows: QuerySet) -> QuerySet:
    return rows.filter(team_id__gte=input.team_id_range.start, team_id__lt=input.team_id_range.end)


def _eligible_team_ids(input: GenerateDigestDataBatchInput) -> set[int]:
    return set(_teams_in_range(input).values_list("id", flat=True))


def _rows_by_team(
    input: GenerateDigestDataBatchInput, rows: QuerySet, eligible_team_ids: set[int]
) -> dict[int, list[dict[str, Any]]]:
    """Group one range-wide query by team, dropping teams the digest does not cover (demo, internal)."""
    rows_by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows_in_range(input, rows):
        if row["team_id"] in eligible_team_ids:
            rows_by_team[row["team_id"]].append(row)
    return rows_by_team


def _limit_per_team(rows: QuerySet, limit: int) -> QuerySet:
    """Keep the `limit` most recently created rows of each team inside one range-wide query."""
    return rows.annotate(
        team_rank=Window(RowNumber(), partition_by=F("team_id"), order_by=F("created_at").desc())
    ).filter(team_rank__lte=limit)


def generate_digest_data_lookup(
    input: GenerateDigestDataBatchInput,
    key_kind: TeamDataKey,
    query_func: Callable[[datetime, datetime], QuerySet],
    resource_type: DigestResourceType,
    per_team_limit: int | None = None,
) -> None:
    logger = _bind_batch_logger(input)
    logger.info("Generating digest data batch", key_kind=key_kind)

    rows: QuerySet = query_func(input.digest.period_start, input.digest.period_end)
    if per_team_limit is not None:
        rows = _limit_per_team(rows, per_team_limit)

    resource_count = 0
    eligible_team_ids = _eligible_team_ids(input)
    payload_by_team: dict[int, str] = {}
    # Teams with nothing new get no key. Aggregation substitutes an empty default for a missing key.
    for team_id, team_rows in _rows_by_team(input, rows, eligible_team_ids).items():
        try:
            digest_data = resource_type.model_validate(team_rows)
        except ValidationError as e:
            logger.warning(
                f"Failed to generate digest data for team {team_id}, skipping...", error=str(e), team_id=team_id
            )
            continue
        payload_by_team[team_id] = digest_data.model_dump_json()
        resource_count += len(digest_data.root)

    with _digest_redis(input.common) as r:
        _store_team_data(r, input, key_kind, payload_by_team, eligible_team_ids)

    logger.info(
        "Finished generating digest data batch",
        key_kind=key_kind,
        resource_count=resource_count,
        team_count=len(payload_by_team),
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

    eligible_team_ids = _eligible_team_ids(input)
    rows_by_team = _rows_by_team(
        input, query_saved_filters(input.digest.period_start, input.digest.period_end), eligible_team_ids
    )
    with redis.Redis.from_url(input.common.django_redis_url) as django_cache:
        playlist_counts = _load_playlist_counts_from_django_cache(
            django_cache, [row["short_id"] for rows in rows_by_team.values() for row in rows]
        )

    payload_by_team: dict[int, str] = {}
    for team_id, rows in rows_by_team.items():
        try:
            filters = FilterList.model_validate(rows)
        except ValidationError as e:
            logger.warning(
                f"Failed to generate Replay filters for team {team_id}, skipping...", error=str(e), team_id=team_id
            )
            continue

        for filter in filters.root:
            playlist_count = playlist_counts.get(filter.short_id)
            if playlist_count is not None:
                filter.recording_count = len(playlist_count.session_ids)
                filter.more_available = playlist_count.has_more

        ordered_filters = filters.order_by_recording_count()
        payload_by_team[team_id] = ordered_filters.model_dump_json()

        team_count += 1
        filter_count += len(ordered_filters.root)

    with _digest_redis(input.common) as r:
        _store_team_data(r, input, TeamDataKey.SAVED_FILTERS, payload_by_team, eligible_team_ids)

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

    eligible_team_ids = _eligible_team_ids(input)
    tag_queries(product=Product.INTERNAL, feature=Feature.DIGEST)
    rows = sync_execute(
        SessionReplayEvents.count_soon_to_expire_sessions_by_team_query(),
        {
            "team_id_start": input.team_id_range.start,
            "team_id_end": input.team_id_range.end,
            "python_now": datetime.now(UTC),
            "ttl_threshold": TTL_THRESHOLD,
        },
        workload=Workload.OFFLINE,
    )

    # Teams without expiring recordings get no key; aggregation defaults the count to zero.
    payload_by_team: dict[int, str] = {}
    recording_count = 0
    for team_id, count in rows:
        if team_id not in eligible_team_ids:
            continue
        expiring_recordings = RecordingCount(recording_count=int(count))
        payload_by_team[team_id] = expiring_recordings.model_dump_json()
        recording_count += expiring_recordings.recording_count

    with _digest_redis(input.common) as r:
        _store_team_data(r, input, TeamDataKey.EXPIRING_RECORDINGS, payload_by_team, eligible_team_ids)

    logger.info(
        "Finished generating Replay recording count batch",
        recording_count=recording_count,
        team_count=len(payload_by_team),
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


# Teams with no events in the current window produce no usage section, so one range-wide query finds
# the teams worth a per-team HogQL query. HogQL cannot express this: it guards every table by team.
ACTIVE_TEAMS_QUERY = """
SELECT team_id
FROM events
WHERE team_id >= %(team_id_start)s AND team_id < %(team_id_end)s
    AND timestamp >= %(period_start)s AND timestamp < %(period_end)s
GROUP BY team_id
"""


def _active_team_ids(input: GenerateDigestDataBatchInput) -> set[int]:
    tag_queries(product=Product.INTERNAL, feature=Feature.DIGEST)
    rows = sync_execute(
        ACTIVE_TEAMS_QUERY,
        {
            "team_id_start": input.team_id_range.start,
            "team_id_end": input.team_id_range.end,
            "period_start": input.digest.period_start,
            "period_end": input.digest.period_end,
        },
        workload=Workload.OFFLINE,
    )
    return {int(team_id) for (team_id,) in rows}


def _query_team_usage_trends(team: Team, period_start: datetime, period_end: datetime) -> UsageTrends | None:
    """Run the per-team usage snapshot on the offline cluster. Returns None for inactive teams."""
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

    attempted = 0
    error_count = 0

    eligible_team_ids = _eligible_team_ids(input)
    active_team_ids = _active_team_ids(input) & eligible_team_ids
    # execute_hogql_query reads several team columns, so load the active teams in full rather than
    # through the trimmed digest queryset.
    active_teams = Team.objects.filter(id__in=active_team_ids).order_by("id")

    payload_by_team: dict[int, str] = {}
    for team in active_teams:
        attempted += 1
        try:
            usage_trends = _query_team_usage_trends(team, input.digest.period_start, input.digest.period_end)
        except Exception as e:
            error_count += 1
            logger.warning(
                f"Failed to generate usage trends for team {team.id}, skipping...",
                error=str(e),
                team_id=team.id,
            )
            continue

        if usage_trends is not None:
            payload_by_team[team.id] = usage_trends.model_dump_json()

    # A malformed query (or an offline-cluster outage) fails for every team, which would
    # otherwise look identical to "no active teams" and silently ship an empty section for
    # the whole batch. Surface it so the activity retries and then fails the run loudly.
    if attempted > 0 and error_count == attempted:
        raise RuntimeError(f"Usage trends query failed for all {attempted} teams in batch")

    with _digest_redis(input.common) as r:
        _store_team_data(r, input, TeamDataKey.USAGE_TRENDS, payload_by_team, eligible_team_ids)

    logger.info("Finished generating usage trends batch", team_count=len(payload_by_team), error_count=error_count)


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

    # Without ACCESS_CONTROL every team of an organization has the same users, and locks are
    # organization-scoped, so resolve both once per organization instead of once per team.
    org_users: dict[UUID, tuple[list[User], dict[int, dict[GovernedSetting, bool]]]] = {}

    def users_and_locks(team: Team) -> tuple[list[User], dict[int, dict[GovernedSetting, bool]]]:
        cacheable = not team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL)
        if cacheable and team.organization_id in org_users:
            return org_users[team.organization_id]
        users = list(team.all_users_with_access())
        locks = notification_locks_for_users([user.id for user in users], organization_id=team.organization_id)
        if cacheable:
            org_users[team.organization_id] = (users, locks)
        return users, locks

    with _digest_redis(input.common) as r:
        for team in _teams_in_range(input, with_organization=True):
            try:
                users, locks_by_user = users_and_locks(team)
                with r.pipeline(transaction=False) as pipe:
                    for user in users:
                        if should_send_notification(
                            user,
                            NotificationSetting.WEEKLY_PROJECT_DIGEST.value,
                            team.id,
                            locks=locks_by_user.get(user.id, {}),
                        ):
                            key = user_data_key(input.digest.key, UserDataKey.NOTIFY_TEAMS, user.id)
                            pipe.sadd(key, team.id)
                            pipe.expire(key, input.common.redis_ttl)

                        user_count += 1
                    pipe.execute()
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

    teams = list(_teams_in_range(input, with_organization=True))
    # The query returns the newest campaign first, so the first row seen per org is the one to keep.
    campaign_by_org: dict[str, dict[str, Any]] = {}
    for campaign in query_product_push_campaigns_for_organizations(
        {team.organization_id for team in teams}, input.digest.period_end
    ):
        campaign_by_org.setdefault(str(campaign["organization_id"]), campaign)

    with _digest_redis(input.common) as r:
        for team in teams:
            try:
                organization_id = str(team.organization_id)
                campaign = campaign_by_org.get(organization_id)
                if campaign is None:
                    team_count += 1
                    continue

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


# Positions follow TeamDataKey order and the TeamDigest constructor below.
TEAM_DATA_DEFAULTS: list[tuple[TeamDataKey, Any]] = [
    (TeamDataKey.DASHBOARDS, DashboardList(root=[])),
    (TeamDataKey.EVENT_DEFINITIONS, EventDefinitionList(root=[])),
    (TeamDataKey.EXPERIMENTS_LAUNCHED, ExperimentList(root=[])),
    (TeamDataKey.EXPERIMENTS_COMPLETED, ExperimentList(root=[])),
    (TeamDataKey.EXTERNAL_DATA_SOURCES, ExternalDataSourceList(root=[])),
    (TeamDataKey.FEATURE_FLAGS, FeatureFlagList(root=[])),
    (TeamDataKey.SAVED_FILTERS, FilterList(root=[])),
    (TeamDataKey.EXPIRING_RECORDINGS, RecordingCount(recording_count=0)),
    (TeamDataKey.SURVEYS_LAUNCHED, SurveyList(root=[])),
    (TeamDataKey.USAGE_TRENDS, UsageTrends()),
    (TeamDataKey.ERROR_ISSUES, ErrorIssueList(root=[])),
]


def _load_team_values(r: redis.Redis, digest_key: str, teams: Sequence[Team]) -> dict[int, list[str | None]]:
    """One Redis read for every team-level key in the batch, in TEAM_DATA_DEFAULTS order per team."""
    keys = [team_data_key(digest_key, kind, team.id) for team in teams for kind, _ in TEAM_DATA_DEFAULTS]
    values = _mget_chunked(r, keys)

    kinds_per_team = len(TEAM_DATA_DEFAULTS)
    return {team.id: values[index * kinds_per_team : (index + 1) * kinds_per_team] for index, team in enumerate(teams)}


def _team_digest(team: Team, raw_values: list[str | None]) -> TeamDigest:
    # Parsing happens per organization, inside its exception boundary, so one malformed value
    # skips that organization instead of the whole batch. Absent keys fall back to the defaults.
    digest_data = [
        default if value is None else default.__class__.model_validate_json(value)
        for (_, default), value in zip(TEAM_DATA_DEFAULTS, raw_values)
    ]
    return TeamDigest(
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


def _generate_organization_digest_batch(input: GenerateOrganizationDigestInput) -> None:
    bind_contextvars(digest_key=input.digest.key, batch_start=input.batch[0], batch_end=input.batch[1])
    logger = LOGGER.bind()
    logger.info("Generating organization-level digest batch")

    organization_count = 0
    team_count = 0

    batch_start, batch_end = input.batch
    organizations = list(query_orgs_for_digest()[batch_start:batch_end])
    teams_by_org: dict[UUID, list[Team]] = defaultdict(list)
    for team in query_teams_for_organizations([organization.id for organization in organizations]):
        teams_by_org[team.organization_id].append(team)

    items: list[tuple[str, str]] = []
    with _digest_redis(input.common) as r:
        team_values = _load_team_values(
            r, input.digest.key, [team for teams in teams_by_org.values() for team in teams]
        )

        for organization in organizations:
            try:
                team_digests = [
                    _team_digest(team, team_values[team.id]) for team in teams_by_org.get(organization.id, [])
                ]
                org_digest = OrganizationDigest(
                    id=organization.id,
                    name=organization.name,
                    created_at=organization.created_at,
                    team_digests=team_digests,
                )
                items.append((org_digest_key(input.digest.key, organization.id), org_digest.model_dump_json()))

                organization_count += 1
                team_count += len(team_digests)
            except Exception as e:
                logger.warning(
                    f"Failed to generate organization-level digest for organization {organization.id}, skipping...",
                    error=str(e),
                    org_id=organization.id,
                )
                continue

        _setex_many(r, input.common.redis_ttl, items)

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
# The SDK queue holds 10,000 events. Draining well below that keeps `capture` from dropping events on a
# full queue, and bounds how many unconfirmed events an abandoned attempt leaves behind.
DRAIN_EVENT_COUNT = 500
# The SDK consumer drops an event above MAX_MSG_SIZE without calling on_error. The margin covers the fields
# the SDK adds around the properties.
DIGEST_PAYLOAD_SIZE_LIMIT = MAX_MSG_SIZE - 16 * 1024
UPLOAD_CLEANUP_SECONDS = 120
DRAIN_SLICE_SECONDS = 5


# These derive from BaseException, so that the per-organization `except Exception` handler cannot swallow them.
class ActivityCancelled(BaseException):
    pass


class UploadDeadlineExceeded(BaseException):
    pass


def _raise_if_cancelled() -> None:
    if activity.in_activity() and activity.is_cancelled():
        raise ActivityCancelled


def _upload_deadline() -> float:
    if not activity.in_activity():
        return math.inf
    info = activity.info()
    if info.start_to_close_timeout is None:
        return math.inf
    remaining = info.started_time + info.start_to_close_timeout - datetime.now(UTC)
    return time.monotonic() + remaining.total_seconds() - UPLOAD_CLEANUP_SECONDS


def _drain(ph_client: Posthog, deadline: float) -> bool:
    # `flush` returns silently with events still queued once its budget runs out. A slice that returns
    # before its budget ends has emptied the queue, and short slices let a cancellation stop the wait.
    while True:
        _raise_if_cancelled()
        budget = min(DRAIN_SLICE_SECONDS, deadline - time.monotonic())
        if budget <= 0:
            return False
        started = time.monotonic()
        ph_client.flush(timeout_seconds=budget)
        if time.monotonic() - started < budget:
            return True


def _send_weekly_digest_batch(input: SendWeeklyDigestBatchInput) -> None:
    bind_contextvars(digest_key=input.digest.key, batch_start=input.batch[0], batch_end=input.batch[1])
    logger = LOGGER.bind()
    logger.info("Sending weekly digest batch")

    sent_digest_count = 0
    empty_org_digest_count = 0
    empty_user_digest_count = 0

    # The SDK marks a batch done whether or not its upload succeeded, so this callback and the value
    # `capture` returns are the only delivery signals. Every event carries organization_id in its payload.
    failed_organization_ids: set[str] = set()

    def on_upload_error(error: Exception, items: list[dict[str, Any]]) -> None:
        failed_organization_ids.update(str(item.get("properties", {}).get("organization_id")) for item in items)
        logger.warning("Failed to upload digest events", error=str(error), event_count=len(items))

    # Only US deployment forwards email events to customer.io
    ph_client: Posthog | None = get_ph_client(region="US", on_error=on_upload_error)

    if not ph_client and not input.dry_run:
        logger.error("Failed to set up Posthog client")
        return

    messaging_record_batch: list[tuple[str, MessagingRecord]] = []
    deadline = _upload_deadline()
    queued_event_count = 0

    def drain() -> None:
        nonlocal queued_event_count
        if ph_client is not None and not _drain(ph_client, deadline):
            raise UploadDeadlineExceeded
        queued_event_count = 0

    def record_sent(records: list[tuple[str, MessagingRecord]]) -> None:
        # An organization whose events failed to upload keeps sent_at empty, so the next attempt resends it.
        drain()
        delivered = [record for organization_id, record in records if organization_id not in failed_organization_ids]
        if len(delivered) < len(records):
            logger.warning(
                "Leaving organizations unsent after failed uploads", organization_count=len(records) - len(delivered)
            )
        MessagingRecord.objects.bulk_update(delivered, ["sent_at"])

    try:
        with _digest_redis(input.common) as r:
            batch_start, batch_end = input.batch
            for organization in query_orgs_for_digest()[batch_start:batch_end]:
                _raise_if_cancelled()
                partial = False
                try:
                    raw_digest: str | None = r.get(org_digest_key(input.digest.key, organization.id))

                    if not raw_digest:
                        logger.warning(
                            "Missing digest data for organization, skipping...", organization_id=organization.id
                        )
                        continue

                    org_digest: OrganizationDigest = OrganizationDigest.model_validate_json(raw_digest)

                    if org_digest.is_empty() or org_digest.count_items() < DIGEST_ITEM_COUNT_THRESHOLD:
                        logger.warning(
                            "Got empty digest for organization, skipping...", organization_id=organization.id
                        )
                        empty_org_digest_count += 1
                        continue

                    messaging_record, created = MessagingRecord.objects.get_or_create(
                        raw_email=f"org_{organization.id}", campaign_key=input.digest.key
                    )

                    if not created and messaging_record.sent_at and not input.allow_already_sent:
                        logger.info(
                            "Digest already sent for organization, skipping...", organization_id=organization.id
                        )
                        continue

                    members = list(query_org_members(organization))
                    with r.pipeline(transaction=False) as pipe:
                        for member in members:
                            pipe.smembers(user_data_key(input.digest.key, UserDataKey.NOTIFY_TEAMS, member.user.id))
                            pipe.get(user_data_key(input.digest.key, UserDataKey.PRODUCT_SUGGESTION, member.user.id))
                        member_data = pipe.execute()

                    for index, member in enumerate(members):
                        _raise_if_cancelled()
                        user = member.user
                        user_notify_teams: set[int] = set(map(int, member_data[index * 2]))

                        # Load user-specific context
                        product_suggestion: DigestProductSuggestion | None = None
                        raw_suggestion: str | None = member_data[index * 2 + 1]
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
                        elif len(json.dumps(payload, default=str).encode()) > DIGEST_PAYLOAD_SIZE_LIMIT:
                            logger.error(
                                "Digest exceeds the event size limit, leaving the organization unsent",
                                organization_id=organization.id,
                                user_id=user.id,
                            )
                            failed_organization_ids.add(str(organization.id))
                            continue
                        elif ph_client is not None:
                            partial = True
                            queued = ph_client.capture(
                                distinct_id=user.distinct_id,
                                event="transactional email",
                                properties=payload,
                                groups={
                                    "organization": str(organization.id),
                                    "instance": settings.SITE_URL,
                                },
                            )
                            if queued is None:
                                failed_organization_ids.add(str(organization.id))
                            queued_event_count += 1
                            if queued_event_count >= DRAIN_EVENT_COUNT:
                                drain()

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
                        messaging_record_batch.append((str(organization.id), messaging_record))

                    if len(messaging_record_batch) >= RECORD_BATCH_SIZE:
                        record_sent(messaging_record_batch)
                        messaging_record_batch = []

        if len(messaging_record_batch) > 0:
            record_sent(messaging_record_batch)

    finally:
        if ph_client is not None:
            ph_client.shutdown()

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
