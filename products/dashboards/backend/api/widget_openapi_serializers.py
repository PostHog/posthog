from __future__ import annotations

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from products.dashboards.backend.constants import (
    DEFAULT_WIDGET_LIST_LIMIT,
    MAX_WIDGET_RESULT_LIMIT,
    WIDGET_DATE_FROM_VALUES,
)
from products.dashboards.backend.widgets.error_tracking_list import ERROR_TRACKING_ORDER_BY
from products.dashboards.backend.widgets.session_replay_list import SESSION_REPLAY_ORDER_BY

_ERROR_TRACKING_WIDGET_STATUS_CHOICES = [
    "archived",
    "active",
    "resolved",
    "pending_release",
    "suppressed",
    "all",
]


class WidgetDateRangeSerializer(serializers.Serializer):
    date_from = serializers.ChoiceField(
        choices=sorted(WIDGET_DATE_FROM_VALUES),
        required=False,
        allow_null=True,
        help_text="Relative lookback window (for example '-7d'). Omit to use the project default range.",
    )


class ErrorTrackingListWidgetConfigSerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        min_value=1,
        max_value=MAX_WIDGET_RESULT_LIMIT,
        default=DEFAULT_WIDGET_LIST_LIMIT,
        required=False,
        help_text="Maximum number of issues to return.",
    )
    orderBy = serializers.ChoiceField(
        choices=sorted(ERROR_TRACKING_ORDER_BY),
        default="occurrences",
        required=False,
        help_text="Issue ranking column.",
    )
    orderDirection = serializers.ChoiceField(
        choices=["ASC", "DESC"],
        default="DESC",
        required=False,
        help_text="Sort direction for orderBy.",
    )
    status = serializers.ChoiceField(
        choices=_ERROR_TRACKING_WIDGET_STATUS_CHOICES,
        default="active",
        required=False,
        help_text="Issue status filter.",
    )
    dateRange = WidgetDateRangeSerializer(
        required=False,
        allow_null=True,
        help_text="Optional relative date range override.",
    )
    filterTestAccounts = serializers.BooleanField(
        required=False,
        help_text="When omitted, follows the project default for filtering test accounts.",
    )


class SessionReplayListWidgetConfigSerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        min_value=1,
        max_value=MAX_WIDGET_RESULT_LIMIT,
        default=DEFAULT_WIDGET_LIST_LIMIT,
        required=False,
        help_text="Maximum number of recordings to return.",
    )
    orderBy = serializers.ChoiceField(
        choices=sorted(SESSION_REPLAY_ORDER_BY),
        default="start_time",
        required=False,
        help_text="Recording ranking column.",
    )
    orderDirection = serializers.ChoiceField(
        choices=["ASC", "DESC"],
        default="DESC",
        required=False,
        help_text="Sort direction for orderBy.",
    )
    dateRange = WidgetDateRangeSerializer(
        required=False,
        allow_null=True,
        help_text="Optional relative date range override.",
    )
    filterTestAccounts = serializers.BooleanField(
        required=False,
        help_text="When omitted, follows the project default for filtering test accounts.",
    )


_DashboardWidgetConfigOpenApi = PolymorphicProxySerializer(
    component_name="DashboardWidgetConfig",
    serializers=[
        ErrorTrackingListWidgetConfigSerializer,
        SessionReplayListWidgetConfigSerializer,
    ],
    resource_type_field_name=None,
)


@extend_schema_field(_DashboardWidgetConfigOpenApi)
class DashboardWidgetConfigField(serializers.JSONField):
    """JSONField annotated with per-widget-type config schemas for OpenAPI generation.

    Runtime validation uses validate_widget_config; this field only improves generated
    client/MCP schemas so agents can see the supported config shapes.
    """

    pass
