from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from products.dashboards.backend.widget_specs.configs import (
    ACTIVITY_EVENTS_LIST_WIDGET_TYPE,
    ERROR_TRACKING_LIST_WIDGET_TYPE,
    SESSION_REPLAY_LIST_WIDGET_TYPE,
    ActivityEventsListWidgetConfig,
    ErrorTrackingListWidgetConfig,
    SessionReplayListWidgetConfig,
)

DashboardWidgetType = Literal["activity_events_list", "error_tracking_list", "session_replay_list"]

__all__ = [
    "DashboardWidgetType",
    "EXPECTED_WIDGET_TYPES",
    "WidgetRegistryEntry",
    "WidgetSpec",
    "WIDGET_SPECS",
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
    from products.dashboards.backend.widgets.session_replay_list import run_session_replay_list_widget  # noqa: PLC0415

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
