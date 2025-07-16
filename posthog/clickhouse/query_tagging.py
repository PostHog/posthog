# This module is responsible for adding tags/metadata to outgoing clickhouse queries in a thread-safe manner
import contextvars
import uuid
from enum import StrEnum
from collections.abc import Generator
from contextlib import contextmanager, suppress

from pydantic import BaseModel, ConfigDict
from typing import Any, Optional

# from posthog.clickhouse.client.connection import Workload
# from posthog.schema import PersonsOnEventsMode

from cachetools import cached


class AccessMethod(StrEnum):
    PERSONAL_API_KEY = "personal_api_key"
    OAUTH = "oauth"


class Product(StrEnum):
    API = "api"
    BATCH_EXPORT = "batch_export"
    FEATURE_FLAGS = "feature_flags"
    MAX_AI = "max_ai"
    PRODUCT_ANALYTICS = "product_analytics"
    REPLAY = "replay"
    SESSION_SUMMARY = "session_summary"
    WAREHOUSE = "warehouse"


class Feature(StrEnum):
    COHORT = "cohort"
    QUERY = "query"
    INSIGHT = "insight"
    DASHBOARD = "dashboard"
    CACHE_WARMUP = "cache_warmup"


class TemporalTags(BaseModel):
    """
    Tags for temporalio workflows and activities.
    """

    workflow_namespace: Optional[str] = None
    workflow_type: Optional[str] = None
    workflow_id: Optional[str] = None
    workflow_run_id: Optional[str] = None
    activity_type: Optional[str] = None
    activity_id: Optional[str] = None
    attempt: Optional[int] = None

    model_config = ConfigDict(validate_assignment=True, use_enum_values=True)


class DagsterTags(BaseModel):
    """
    Tags for Dagster runs

    Check: https://docs.dagster.io/api/dagster/internals#dagster.DagsterRun
    """

    job_name: Optional[str] = None
    run_id: Optional[str] = None
    tags: Optional[dict[str, str]] = None
    root_run_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    job_snapshot_id: Optional[str] = None
    execution_plan_snapshot_id: Optional[str] = None

    op_name: Optional[str] = None
    asset_key: Optional[str] = None


class QueryTags(BaseModel):
    team_id: Optional[int] = None
    user_id: Optional[int] = None
    access_method: Optional[AccessMethod] = None
    org_id: Optional[uuid.UUID] = None
    product: Optional[Product] = None

    # at this moment: request for HTTP request, celery, dagster and temporal are used, please don't use others.
    kind: Optional[str] = None
    id: Optional[str] = None
    session_id: Optional[uuid.UUID] = None

    # temporalio tags
    temporal: Optional[TemporalTags] = None
    # dagster specific tags
    dagster: Optional[DagsterTags] = None

    query: Optional[object] = None
    query_settings: Optional[object] = None
    query_time_range_days: Optional[int] = None
    query_type: Optional[str] = None

    route_id: Optional[str] = None
    workload: Optional[str] = None  # enum connection.Workload
    dashboard_id: Optional[int] = None
    insight_id: Optional[int] = None
    chargeable: Optional[int] = None
    name: Optional[str] = None

    http_referer: Optional[str] = None
    http_request_id: Optional[uuid.UUID] = None
    http_user_agent: Optional[str] = None

    alert_config_id: Optional[uuid.UUID] = None
    batch_export_id: Optional[uuid.UUID] = None
    cache_key: Optional[str] = None
    celery_task_id: Optional[uuid.UUID] = None
    clickhouse_exception_type: Optional[str] = None
    client_query_id: Optional[str] = None
    cohort_id: Optional[int] = None
    entity_math: Optional[list[str]] = None

    # replays
    replay_playlist_id: Optional[int] = None

    # experiments
    experiment_feature_flag_key: Optional[str] = None
    experiment_id: Optional[int] = None
    experiment_name: Optional[str] = None
    experiment_is_data_warehouse_query: Optional[bool] = None

    feature: Optional[Feature] = None
    filter: Optional[object] = None
    filter_by_type: Optional[list[str]] = None
    breakdown_by: Optional[list[str]] = None

    # data warehouse
    trend_volume_display: Optional[str] = None
    table_id: Optional[uuid.UUID] = None
    warehouse_query: Optional[bool] = None

    trend_volume_type: Optional[str] = None

    has_joins: Optional[bool] = None
    has_json_operations: Optional[bool] = None

    modifiers: Optional[object] = None
    number_of_entities: Optional[int] = None
    person_on_events_mode: Optional[str] = None  # PersonsOnEventsMode

    timings: Optional[dict[str, float]] = None
    trigger: Optional[str] = None

    # used by billing
    usage_report: Optional[str] = None

    user_email: Optional[str] = None

    # constant query tags
    git_commit: Optional[str] = None
    container_hostname: Optional[str] = None
    service_name: Optional[str] = None

    model_config = ConfigDict(validate_assignment=True, use_enum_values=True)

    def update(self, **kwargs):
        for field, value in kwargs.items():
            setattr(self, field, value)

    def with_temporal(self, temporal_tags: TemporalTags):
        self.kind = "temporal"
        self.temporal = temporal_tags

    def with_dagster(self, dagster_tags: DagsterTags):
        """Tags for dagster runs and activities."""
        self.kind = "dagster"
        self.dagster = dagster_tags

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True)


query_tags: contextvars.ContextVar = contextvars.ContextVar("query_tags")


@cached(cache={})
def __get_constant_tags() -> dict[str, str]:
    # import locally to avoid circular imports
    from posthog.settings import CONTAINER_HOSTNAME, TEST, OTEL_SERVICE_NAME

    if TEST:
        return {"git_commit": "test", "container_hostname": "test", "service_name": "test"}

    from posthog.git import get_git_commit_short

    return {
        "git_commit": get_git_commit_short() or "",
        "container_hostname": CONTAINER_HOSTNAME,
        "service_name": OTEL_SERVICE_NAME or "",
    }


def create_base_tags(**kwargs) -> QueryTags:
    return QueryTags(**{**kwargs, **__get_constant_tags()})


def get_query_tags() -> QueryTags:
    try:
        qt = query_tags.get()
    except LookupError:
        qt = create_base_tags()
        query_tags.set(qt)
    return qt


def get_query_tag_value(key: str) -> Optional[Any]:
    try:
        return getattr(get_query_tags(), key)
    except (AttributeError, KeyError):
        return None


def update_tags(query_tags: QueryTags):
    get_query_tags().update(**query_tags.model_dump(exclude_none=True))


def tag_queries(**kwargs) -> None:
    """
    The purpose of tag_queries is to pass additional context for ClickHouse executed queries. The tags
    are serialized into ClickHouse' system.query_log.log_comment column.

    :param kwargs: Key->value pairs of tags to be set.
    """
    get_query_tags().update(**kwargs)


def clear_tag(key):
    with suppress(LookupError):
        qt = query_tags.get()
        setattr(qt, key, None)


def reset_query_tags():
    query_tags.set(create_base_tags())


class QueryCounter:
    def __init__(self):
        self.total_query_time = 0.0

    @property
    def query_time_ms(self):
        return self.total_query_time * 1000

    def __call__(self, execute, *args, **kwargs):
        import time

        start_time = time.perf_counter()

        try:
            return execute(*args, **kwargs)
        finally:
            self.total_query_time += time.perf_counter() - start_time


@contextmanager
def tags_context(**tags_to_set: Any) -> Generator[None, None, None]:
    """
    Context manager that saves all query tags on enter and restores them on exit.
    Optionally accepts key-value pairs to set after saving the original tags.

    Usage:
    ```python
    with tags_context(foo='bar', baz='qux'):
        # tags are saved, new tags are set
        # do stuff with tags
        # tags will be restored to original state after context
    ```
    """
    tags_copy: Optional[QueryTags] = None
    try:
        tags_copy = get_query_tags().model_copy(deep=True)
        if tags_to_set:
            tag_queries(**tags_to_set)
        yield
    finally:
        if tags_copy:
            query_tags.set(tags_copy)
