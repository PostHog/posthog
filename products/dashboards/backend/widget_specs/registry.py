from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from products.dashboards.backend.widget_specs.configs import (
    ACTIVITY_EVENTS_LIST_WIDGET_TYPE,
    ERROR_TRACKING_LIST_WIDGET_TYPE,
    EXPERIMENT_RESULTS_WIDGET_TYPE,
    EXPERIMENTS_LIST_WIDGET_TYPE,
    LOGS_LIST_WIDGET_TYPE,
    SESSION_REPLAY_LIST_WIDGET_TYPE,
    SURVEY_RESULTS_WIDGET_TYPE,
    ActivityEventsListWidgetConfig,
    ErrorTrackingListWidgetConfig,
    ExperimentResultsWidgetConfig,
    ExperimentsListWidgetConfig,
    LogsListWidgetConfig,
    SessionReplayListWidgetConfig,
    SurveyResultsWidgetConfig,
)

DashboardWidgetType = Literal[
    "activity_events_list",
    "error_tracking_list",
    "session_replay_list",
    "experiments_list",
    "experiment_results",
    "survey_results",
    "logs_list",
]

__all__ = [
    "DashboardWidgetType",
    "EXPECTED_WIDGET_TYPES",
    "WidgetRegistryEntry",
    "WidgetSpec",
    "WIDGET_SPECS",
    "count_active_widget_filters",
    "extract_widget_filters",
    "get_widget_registry_entry",
    "get_widget_spec",
    "validate_widget_config",
]


@dataclass(frozen=True)
class WidgetSpec:
    widget_type: str
    config_model: type[BaseModel]
    query_fn: Callable[..., dict[str, Any]]
    required_scopes: tuple[str, ...]
    group_id: str
    group_label: str
    label: str
    description: str
    required_product_access: str | None
    product_access_denied_message: str | None
    availability_requirements: tuple[str, ...]
    form_fields: tuple[str, ...]
    # Config keys whose value represents an on-tile filter. A change to any of these emits the
    # "dashboard widget filters updated" analytics event. Filters stored under a single `widgetFilters`
    # record list that key; widgets that keep filters as top-level config keys (e.g. experiments) list each.
    filter_fields: tuple[str, ...]


# Status filters use this sentinel for "no status filter applied" — it must not count as an active filter.
_STATUS_ANY_SENTINEL = "all"


def validate_widget_config(widget_type: str, config: dict[str, Any]) -> dict[str, Any]:
    spec = WIDGET_SPECS.get(widget_type)
    if spec is None:
        raise DRFValidationError({"widget_type": f"Unknown widget type: {widget_type}"})
    try:
        validated = spec.config_model.model_validate(config)
    except ValidationError as exc:
        message = "; ".join(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors())
        raise DRFValidationError({"config": message or "Invalid widget config."}) from exc
    return validated.model_dump(mode="json", exclude_none=True)


def _load_widget_specs() -> dict[str, WidgetSpec]:
    # Runners import validate_widget_config from this module — keep runner imports local to
    # avoid import cycles (runners ↔ registry).
    from products.dashboards.backend.widgets.activity_events_list import (  # noqa: PLC0415
        run_activity_events_list_widget,
    )
    from products.dashboards.backend.widgets.error_tracking_list import run_error_tracking_list_widget  # noqa: PLC0415
    from products.dashboards.backend.widgets.experiment_results import run_experiment_results_widget  # noqa: PLC0415
    from products.dashboards.backend.widgets.experiments_list import run_experiments_list_widget  # noqa: PLC0415
    from products.dashboards.backend.widgets.logs_list import run_logs_list_widget  # noqa: PLC0415
    from products.dashboards.backend.widgets.session_replay_list import run_session_replay_list_widget  # noqa: PLC0415
    from products.dashboards.backend.widgets.survey_results import run_survey_results_widget  # noqa: PLC0415

    return {
        ACTIVITY_EVENTS_LIST_WIDGET_TYPE: WidgetSpec(
            widget_type=ACTIVITY_EVENTS_LIST_WIDGET_TYPE,
            config_model=ActivityEventsListWidgetConfig,
            query_fn=run_activity_events_list_widget,
            required_scopes=("query:read",),
            group_id="activity",
            group_label="Activity",
            label="Recent events",
            description="Latest events captured in this project, as on Activity > Explore.",
            required_product_access=None,
            product_access_denied_message=None,
            availability_requirements=(),
            form_fields=("limit", "dateRange", "filterTestAccounts"),
            filter_fields=("eventName",),
        ),
        ERROR_TRACKING_LIST_WIDGET_TYPE: WidgetSpec(
            widget_type=ERROR_TRACKING_LIST_WIDGET_TYPE,
            config_model=ErrorTrackingListWidgetConfig,
            query_fn=run_error_tracking_list_widget,
            required_scopes=("error_tracking:read",),
            group_id="error_tracking",
            group_label="Error tracking",
            label="Top issues",
            description="Ranked list of the most impactful error tracking issues.",
            required_product_access="error_tracking",
            product_access_denied_message="You do not have access to error tracking.",
            availability_requirements=("exception_autocapture",),
            form_fields=("limit", "orderBy", "orderDirection", "dateRange", "filterTestAccounts", "status"),
            filter_fields=("widgetFilters",),
        ),
        SESSION_REPLAY_LIST_WIDGET_TYPE: WidgetSpec(
            widget_type=SESSION_REPLAY_LIST_WIDGET_TYPE,
            config_model=SessionReplayListWidgetConfig,
            query_fn=run_session_replay_list_widget,
            required_scopes=("session_recording:read",),
            group_id="session_replay",
            group_label="Session replay",
            label="Recent recordings",
            description="Recent session recordings you can open in the replay player.",
            required_product_access="session_recording",
            product_access_denied_message="You do not have access to session replay.",
            availability_requirements=("session_replay_enabled",),
            form_fields=("limit", "orderBy", "orderDirection", "dateRange", "filterTestAccounts"),
            filter_fields=("widgetFilters",),
        ),
        EXPERIMENTS_LIST_WIDGET_TYPE: WidgetSpec(
            widget_type=EXPERIMENTS_LIST_WIDGET_TYPE,
            config_model=ExperimentsListWidgetConfig,
            query_fn=run_experiments_list_widget,
            required_scopes=("experiment:read",),
            group_id="experiments",
            group_label="Experiments",
            label="Experiments list",
            description="List of experiments filtered by status and creator.",
            required_product_access="experiment",
            product_access_denied_message="You do not have access to experiments.",
            availability_requirements=(),
            form_fields=("limit", "orderBy", "orderDirection", "status", "createdBy"),
            filter_fields=("status", "createdBy"),
        ),
        EXPERIMENT_RESULTS_WIDGET_TYPE: WidgetSpec(
            widget_type=EXPERIMENT_RESULTS_WIDGET_TYPE,
            config_model=ExperimentResultsWidgetConfig,
            query_fn=run_experiment_results_widget,
            required_scopes=("experiment:read",),
            group_id="experiments",
            group_label="Experiments",
            label="Experiment results",
            description="Current results for the primary metrics of a selected experiment.",
            required_product_access="experiment",
            product_access_denied_message="You do not have access to experiments.",
            availability_requirements=(),
            form_fields=("experimentId",),
            filter_fields=("experimentId",),
        ),
        SURVEY_RESULTS_WIDGET_TYPE: WidgetSpec(
            widget_type=SURVEY_RESULTS_WIDGET_TYPE,
            config_model=SurveyResultsWidgetConfig,
            query_fn=run_survey_results_widget,
            required_scopes=("survey:read", "query:read", "person:read"),
            group_id="surveys",
            group_label="Surveys",
            label="Survey results",
            description="Performance stats and recent responses for a selected survey.",
            required_product_access="survey",
            product_access_denied_message="You do not have access to surveys.",
            availability_requirements=(),
            form_fields=("surveyId", "limit", "dateRange"),
            # surveyId is chosen on the tile filter bar (like experiment_results' experimentId), so it
            # counts as a filter change — include it so "dashboard widget filters updated" fires on re-pick.
            filter_fields=("surveyId", "dateRange"),
        ),
        LOGS_LIST_WIDGET_TYPE: WidgetSpec(
            widget_type=LOGS_LIST_WIDGET_TYPE,
            config_model=LogsListWidgetConfig,
            query_fn=run_logs_list_widget,
            required_scopes=("logs:read",),
            group_id="logs",
            group_label="Logs",
            label="Recent logs",
            description="Latest log lines, filterable by severity level and service.",
            required_product_access="logs",
            product_access_denied_message="You do not have access to logs.",
            # No cheap team-flag setup check for logs (availability would need a ClickHouse
            # has-logs query, which we keep off the widget-add path) — leave ungated like activity.
            availability_requirements=(),
            form_fields=("limit", "dateRange", "wrapLines", "timezone"),
            filter_fields=("severityLevels", "serviceNames"),
        ),
    }


WIDGET_SPECS: dict[str, WidgetSpec] = _load_widget_specs()

EXPECTED_WIDGET_TYPES = frozenset(WIDGET_SPECS.keys())


class WidgetRegistryEntry(TypedDict):
    query_fn: Callable[..., dict[str, Any]]
    required_scopes: list[str]
    required_product_access: NotRequired[str | None]


def get_widget_registry_entry(widget_type: str) -> WidgetRegistryEntry | None:
    spec = WIDGET_SPECS.get(widget_type)
    if spec is None:
        return None
    return {
        "query_fn": spec.query_fn,
        "required_scopes": list(spec.required_scopes),
        "required_product_access": spec.required_product_access,
    }


def get_widget_spec(widget_type: str) -> WidgetSpec | None:
    return WIDGET_SPECS.get(widget_type)


def extract_widget_filters(widget_type: str, config: dict[str, Any] | None) -> dict[str, Any]:
    """Filter-bearing subset of a widget config, used to detect tile-filter changes for analytics."""
    spec = WIDGET_SPECS.get(widget_type)
    if spec is None or config is None:
        return {}
    return {field: config.get(field) for field in spec.filter_fields}


def count_active_widget_filters(widget_type: str, config: dict[str, Any] | None) -> int:
    """How many filters are actively applied on the tile (0 = no filters, e.g. just cleared)."""
    spec = WIDGET_SPECS.get(widget_type)
    if spec is None or config is None:
        return 0
    count = 0
    for field in spec.filter_fields:
        value = config.get(field)
        if isinstance(value, (dict, list)):
            count += len(value)
        elif field == "status":
            if value not in (None, _STATUS_ANY_SENTINEL):
                count += 1
        elif value is not None:
            count += 1
    return count
