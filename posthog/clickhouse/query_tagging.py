# This module is responsible for adding tags/metadata to outgoing clickhouse queries in a thread-safe manner
import uuid
import contextvars
from collections.abc import Generator
from contextlib import contextmanager, suppress
from enum import StrEnum
from typing import Any

# from posthog.clickhouse.client.connection import Workload
# from posthog.schema import PersonsOnEventsMode
from cachetools import cached
from pydantic import BaseModel, ConfigDict


class AccessMethod(StrEnum):
    PERSONAL_API_KEY = "personal_api_key"
    OAUTH = "oauth"


class Product(StrEnum):
    API = "api"
    BATCH_EXPORT = "batch_export"
    FEATURE_FLAGS = "feature_flags"
    MAX_AI = "max_ai"
    MESSAGING = "messaging"
    PRODUCT_ANALYTICS = "product_analytics"
    REPLAY = "replay"
    SESSION_SUMMARY = "session_summary"
    WAREHOUSE = "warehouse"
    EXPERIMENTS = "experiments"


class Feature(StrEnum):
    BEHAVIORAL_COHORTS = "behavioral_cohorts"
    COHORT = "cohort"
    QUERY = "query"
    INSIGHT = "insight"
    DASHBOARD = "dashboard"
    CACHE_WARMUP = "cache_warmup"
    DATA_MODELING = "data_modeling"
    IMPORT_PIPELINE = "import_pipeline"


class TemporalTags(BaseModel):
    """
    Tags for temporalio workflows and activities.
    """

    workflow_namespace: str | None = None
    workflow_type: str | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    activity_type: str | None = None
    activity_id: str | None = None
    attempt: int | None = None

    model_config = ConfigDict(validate_assignment=True, use_enum_values=True)


class DagsterTags(BaseModel):
    """
    Tags for Dagster runs

    Check: https://docs.dagster.io/api/dagster/internals#dagster.DagsterRun
    """

    job_name: str | None = None
    run_id: str | None = None
    tags: dict[str, str] | None = None
    root_run_id: str | None = None
    parent_run_id: str | None = None
    job_snapshot_id: str | None = None
    execution_plan_snapshot_id: str | None = None

    op_name: str | None = None
    asset_key: str | None = None


class QueryTags(BaseModel):
    team_id: int | None = None
    user_id: int | None = None
    access_method: AccessMethod | None = None
    api_key_mask: str | None = None
    api_key_label: str | None = None
    org_id: uuid.UUID | None = None
    product: Product | None = None

    # at this moment: request for HTTP request, celery, dagster and temporal are used, please don't use others.
    kind: str | None = None
    id: str | None = None
    session_id: uuid.UUID | None = None

    # temporalio tags
    temporal: TemporalTags | None = None
    # dagster specific tags
    dagster: DagsterTags | None = None

    query: object | None = None
    query_settings: object | None = None
    query_time_range_days: int | None = None
    query_type: str | None = None

    route_id: str | None = None
    workload: str | None = None  # enum connection.Workload
    dashboard_id: int | None = None
    insight_id: int | None = None
    exported_asset_id: int | None = None
    export_format: str | None = None
    chargeable: int | None = None
    request_name: str | None = None
    name: str | None = None

    http_referer: str | None = None
    http_request_id: uuid.UUID | None = None
    http_user_agent: str | None = None

    alert_config_id: uuid.UUID | None = None
    batch_export_id: uuid.UUID | None = None
    cache_key: str | None = None
    celery_task_id: uuid.UUID | None = None
    clickhouse_exception_type: str | None = None
    client_query_id: str | None = None
    cohort_id: int | None = None
    entity_math: list[str] | None = None

    # replays
    replay_playlist_id: int | None = None

    # experiments
    experiment_feature_flag_key: str | None = None
    experiment_id: int | None = None
    experiment_name: str | None = None
    experiment_is_data_warehouse_query: bool | None = None

    feature: Feature | None = None
    filter: object | None = None
    filter_by_type: list[str] | None = None
    breakdown_by: list[str] | None = None

    # data warehouse
    trend_volume_display: str | None = None
    table_id: uuid.UUID | None = None
    warehouse_query: bool | None = None

    trend_volume_type: str | None = None

    has_joins: bool | None = None
    has_json_operations: bool | None = None

    modifiers: object | None = None
    number_of_entities: int | None = None
    person_on_events_mode: str | None = None  # PersonsOnEventsMode

    timings: dict[str, float] | None = None
    trigger: str | None = None

    # used by billing
    usage_report: str | None = None

    user_email: str | None = None

    # constant query tags
    git_commit: str | None = None
    container_hostname: str | None = None
    service_name: str | None = None

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
    from posthog.settings import CONTAINER_HOSTNAME, OTEL_SERVICE_NAME, TEST

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


def get_query_tag_value(key: str) -> Any | None:
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
    tags_copy: QueryTags | None = None
    try:
        tags_copy = get_query_tags().model_copy(deep=True)
        if tags_to_set:
            tag_queries(**tags_to_set)
        yield
    finally:
        if tags_copy:
            query_tags.set(tags_copy)
