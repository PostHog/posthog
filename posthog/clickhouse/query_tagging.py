# This module is responsible for adding tags/metadata to outgoing clickhouse queries in a thread-safe manner
import os
import sys
import uuid
import types
import contextvars
from collections.abc import Generator
from contextlib import contextmanager, suppress
from enum import StrEnum
from typing import Any, Optional

# from posthog.clickhouse.client.connection import Workload
# from posthog.schema import PersonsOnEventsMode
from cachetools import cached
from pydantic import BaseModel, ConfigDict

from posthog.schema import ProductKey


class AccessMethod(StrEnum):
    PERSONAL_API_KEY = "personal_api_key"
    OAUTH = "oauth"


class Product(StrEnum):
    API = "api"
    BATCH_EXPORT = "batch_export"
    ENDPOINTS = "endpoints"
    ERROR_TRACKING = "error_tracking"
    EXPERIMENTS = "experiments"
    FEATURE_FLAGS = "feature_flags"
    GROUP_ANALYTICS = "group_analytics"
    LLM_ANALYTICS = "llm_analytics"
    LOGS = "logs"
    MAX_AI = "max_ai"
    MESSAGING = "messaging"
    MOBILE_REPLAY = "mobile_replay"
    PIPELINE_DESTINATIONS = "pipeline_destinations"
    PLATFORM_AND_SUPPORT = "platform_and_support"
    PRODUCT_ANALYTICS = "product_analytics"
    REPLAY = "replay"
    SDK_DOCTOR = "sdk_doctor"
    SESSION_SUMMARY = "session_summary"
    SIGNALS = "signals"
    SURVEYS = "surveys"
    WAREHOUSE = "warehouse"
    WEB_ANALYTICS = "web_analytics"
    WORKFLOWS = "workflows"

    INTERNAL = "internal"  # for internal use only


class Feature(StrEnum):
    BACKFILL = "backfill"
    BEHAVIORAL_COHORTS = "behavioral_cohorts"
    COHORT = "cohort"
    DIGEST = "digest"
    QUERY = "query"  # user-facing queries only
    INSIGHT = "insight"
    DASHBOARD = "dashboard"
    CACHE_WARMUP = "cache_warmup"
    DATA_MODELING = "data_modeling"
    HEALTH_CHECK = "health_check"
    IMPORT_PIPELINE = "import_pipeline"
    PREAGGREGATION = "preaggregation"
    DATA_DELETION = "data_deletion"
    SCHEMA_INTROSPECTION = "schema_introspection"
    USAGE_REPORT = "usage_report"


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
    api_key_mask: Optional[str] = None
    api_key_label: Optional[str] = None
    org_id: Optional[uuid.UUID] = None
    product: Optional[Product | ProductKey] = None

    # at this moment: request for HTTP request, celery, dagster and temporal are used, please don't use others.
    kind: Optional[str] = None
    id: Optional[str] = None
    session_id: Optional[str] = None

    # temporalio tags
    temporal: Optional[TemporalTags] = None
    # dagster specific tags
    dagster: Optional[DagsterTags] = None

    query: Optional[object] = None
    query_settings: Optional[object] = None
    query_time_range_days: Optional[int] = None
    query_type: Optional[str] = None

    rate_limit_bypass: Optional[int] = None
    rate_limit_wait_ms: Optional[int] = None
    kill_switch: Optional[str] = None

    route_id: Optional[str] = None
    workload: Optional[str] = None  # enum connection.Workload
    dashboard_id: Optional[int] = None
    insight_id: Optional[int] = None
    exported_asset_id: Optional[int] = None
    export_format: Optional[str] = None
    chargeable: Optional[int] = None
    request_name: Optional[str] = None
    name: Optional[str] = None

    http_referer: Optional[str] = None
    http_request_id: Optional[uuid.UUID] = None
    http_user_agent: Optional[str] = None

    # frontend UI context (from QueryLogTags)
    scene: Optional[str] = None

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
    execution_mode: Optional[str] = None
    trigger: Optional[str] = None

    # used by billing
    usage_report: Optional[str] = None

    user_email: Optional[str] = None

    is_impersonated: Optional[bool] = None

    # request source and MCP metadata
    source: Optional[str] = None
    mcp_user_agent: Optional[str] = None
    mcp_client_name: Optional[str] = None
    mcp_client_version: Optional[str] = None
    mcp_protocol_version: Optional[str] = None
    mcp_oauth_client_name: Optional[str] = None

    # caller source location (set automatically in sync_execute via stack inspection)
    source_file: Optional[str] = None
    source_line: Optional[int] = None

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


def get_query_tag_value(key: str) -> Optional[Any]:
    try:
        return getattr(get_query_tags(), key)
    except (AttributeError, KeyError):
        return None


def update_tags(new_query_tags: QueryTags):
    current_tags = get_query_tags()
    updated_tags = current_tags.model_copy(deep=True)
    updated_tags.update(**new_query_tags.model_dump(exclude_none=True))
    query_tags.set(updated_tags)


def tag_queries(**kwargs) -> None:
    """
    The purpose of tag_queries is to pass additional context for ClickHouse executed queries. The tags
    are serialized into ClickHouse' system.query_log.log_comment column.

    :param kwargs: Key->value pairs of tags to be set.
    """
    current_tags = get_query_tags()
    updated_tags = current_tags.model_copy(deep=True)
    updated_tags.update(**kwargs)
    query_tags.set(updated_tags)


def clear_tag(key):
    with suppress(LookupError):
        current_tags = query_tags.get()
        updated_tags = current_tags.model_copy(deep=True)
        setattr(updated_tags, key, None)
        query_tags.set(updated_tags)


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


# Stack inspection for source_file / source_line tagging
_THIS_FILE = os.path.abspath(__file__)
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(_THIS_FILE), os.pardir, os.pardir))
_PROJECT_ROOT_PREFIX = _PROJECT_ROOT + os.sep

# Files/directories in the query execution infrastructure to skip when walking the stack
_SOURCE_SKIP_PREFIXES: tuple[str, ...] = (
    os.path.join(_PROJECT_ROOT, "posthog", "clickhouse", "client") + os.sep,
    _THIS_FILE,
    os.path.join(_PROJECT_ROOT, "posthog", "hogql", "query.py"),
    os.path.join(_PROJECT_ROOT, "posthog", "hogql_queries", "insights", "paginators.py"),
    os.path.join(_PROJECT_ROOT, "posthog", "queries", "insight.py"),
    os.path.join(_PROJECT_ROOT, "posthog", "utils.py"),
)

_MAX_CALLER_STACK_DEPTH = 30


def get_caller_source() -> tuple[Optional[str], Optional[int]]:
    """Walk the call stack to find the first caller outside of query execution infrastructure.

    Returns (source_file, source_line) where source_file is relative to the project root,
    or (None, None) if no suitable caller is found.
    """
    try:
        frame: Optional[types.FrameType] = sys._getframe(1)

        for _ in range(_MAX_CALLER_STACK_DEPTH):
            if frame is None:
                break

            filename = frame.f_code.co_filename

            # Only consider frames within the project
            if not filename.startswith(_PROJECT_ROOT_PREFIX):
                frame = frame.f_back
                continue

            # Skip query execution infrastructure
            if any(filename.startswith(prefix) for prefix in _SOURCE_SKIP_PREFIXES):
                frame = frame.f_back
                continue

            return filename[len(_PROJECT_ROOT_PREFIX) :], frame.f_lineno

        return None, None
    except Exception:
        return None, None
