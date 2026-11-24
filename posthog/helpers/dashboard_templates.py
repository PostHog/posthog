from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

from django.db.models import Q

import structlog

from posthog.models.scoping import team_scope
from posthog.models.tag import Tag

from products.dashboards.backend.constants import MAX_TEXT_TILE_AGENT_CONTEXT_LENGTH
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
from products.dashboards.backend.models.dashboard_tile import ButtonTile, DashboardTile, Text
from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.product_analytics.backend.facade.models import Insight

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

DASHBOARD_COLORS: list[str] = ["white", "blue", "green", "purple", "black"]

logger = structlog.get_logger(__name__)

# TODO remove these old methods when the dashboard_templates feature flag is rolled out


def _create_website_dashboard(dashboard: Dashboard) -> None:
    dashboard.filters = {"date_from": "-30d"}
    tag, _ = Tag.objects.get_or_create(
        name="marketing",
        team_id=dashboard.team_id,
        defaults={"team_id": dashboard.team_id},
    )
    dashboard.tagged_items.create(tag_id=tag.id)
    dashboard.save(update_fields=["filters"])

    # row 1
    _create_tile_for_insight(
        dashboard,
        name="Website Unique Users (Total)",
        description="Shows the number of unique users that use your app every day.",
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "compareFilter": {"compare": True},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "BoldNumber",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={
            "sm": {"i": "21", "x": 0, "y": 0, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 0,
                "i": "21",
                "minW": 1,
                "minH": 5,
            },
        },
        color="blue",
    )

    _create_tile_for_insight(
        dashboard,
        name="Organic SEO Unique Users (Total)",
        description="",
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "compareFilter": {"compare": True},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$referring_domain",
                                    "operator": "icontains",
                                    "type": "event",
                                    "value": "google",
                                },
                                {"key": "utm_source", "operator": "is_not_set", "type": "event", "value": "is_not_set"},
                            ],
                        }
                    ],
                },
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "BoldNumber",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={
            "sm": {"i": "22", "x": 6, "y": 0, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 5,
                "i": "22",
                "minW": 1,
                "minH": 5,
            },
        },
        color="green",
    )

    # row 2
    _create_tile_for_insight(
        dashboard,
        name="Website Unique Users (Breakdown)",
        description="",
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "week",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsBar",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={
            "sm": {"i": "23", "x": 0, "y": 5, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 10,
                "i": "23",
                "minW": 1,
                "minH": 5,
            },
        },
        color="blue",
    )

    _create_tile_for_insight(
        dashboard,
        name="Organic SEO Unique Users (Breakdown)",
        description="",
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "week",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [
                    {
                        "event": "$pageview",
                        "kind": "EventsNode",
                        "math": "dau",
                        "name": "$pageview",
                        "properties": [
                            {"key": "$referring_domain", "operator": "icontains", "type": "event", "value": "google"},
                            {"key": "utm_source", "operator": "is_not_set", "type": "event", "value": "is_not_set"},
                        ],
                    }
                ],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsBar",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={
            "sm": {"i": "24", "x": 6, "y": 5, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {"w": 1, "h": 5, "x": 0, "y": 15, "i": "24", "minW": 1, "minH": 5},
        },
        color="green",
    )

    # row 3

    _create_tile_for_insight(
        dashboard,
        name="Sessions Per User",
        description="",
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "week",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [
                    {"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"},
                    {"event": "$pageview", "kind": "EventsNode", "math": "unique_session", "name": "$pageview"},
                ],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsLineGraph",
                    "formula": "B/A",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={
            "sm": {"i": "25", "x": 0, "y": 10, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 20,
                "i": "25",
                "minW": 1,
                "minH": 5,
            },
        },
        color=None,
    )

    _create_tile_for_insight(
        dashboard,
        name="Pages Per User",
        description="",
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "week",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [
                    {"event": "$pageview", "kind": "EventsNode", "math": "total", "name": "$pageview"},
                    {"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"},
                ],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsLineGraph",
                    "formula": "A/B",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={
            "sm": {"i": "26", "x": 6, "y": 10, "w": 6, "h": 5, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 25,
                "i": "26",
                "minW": 1,
                "minH": 5,
            },
        },
        color=None,
    )

    # row 4

    _create_tile_for_insight(
        dashboard,
        name="Top Website Pages (Overall)",
        description="",
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown": "$current_url", "breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "$current_url", "operator": "not_icontains", "type": "event", "value": "?"}
                            ],
                        }
                    ],
                },
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "unique_session", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsBarValue",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={
            "sm": {"i": "27", "x": 0, "y": 15, "w": 6, "h": 8, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 30,
                "i": "27",
                "minW": 1,
                "minH": 5,
            },
        },
        color="black",
    )

    _create_tile_for_insight(
        dashboard,
        name="Top Website Pages (via Google)",
        description="",
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown": "$current_url", "breakdown_type": "event"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "$current_url", "operator": "not_icontains", "type": "event", "value": "?"},
                                {
                                    "key": "$referring_domain",
                                    "operator": "icontains",
                                    "type": "event",
                                    "value": "google",
                                },
                            ],
                        }
                    ],
                },
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "unique_session", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "ActionsBarValue",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={
            "sm": {"i": "28", "x": 6, "y": 15, "w": 6, "h": 8, "minW": 3, "minH": 5},
            "xs": {"w": 1, "h": 5, "x": 0, "y": 35, "i": "28", "minW": 1, "minH": 5},
        },
        color="black",
    )

    # row 5

    _create_tile_for_insight(
        dashboard,
        name="Website Users by Location",
        description="",
        query={
            "kind": "InsightVizNode",
            "source": {
                "breakdownFilter": {"breakdown": "$geoip_country_code", "breakdown_type": "person"},
                "dateRange": {"date_from": "-30d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "day",
                "kind": "TrendsQuery",
                "properties": [],
                "series": [{"event": "$pageview", "kind": "EventsNode", "math": "dau", "name": "$pageview"}],
                "trendsFilter": {
                    "aggregationAxisFormat": "numeric",
                    "display": "WorldMap",
                    "showAlertThresholdLines": False,
                    "showLegend": False,
                    "showPercentStackView": False,
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "yAxisScaleType": "linear",
                },
            },
        },
        layouts={
            "sm": {"i": "29", "x": 0, "y": 23, "w": 12, "h": 8, "minW": 3, "minH": 5},
            "xs": {
                "w": 1,
                "h": 5,
                "x": 0,
                "y": 40,
                "i": "29",
                "minW": 1,
                "minH": 5,
            },
        },
        color=None,
    )


def _create_default_app_items(dashboard: Dashboard) -> None:
    template = DashboardTemplate.original_template()
    create_from_template(dashboard, template)


DASHBOARD_TEMPLATES: dict[str, Callable] = {
    "DEFAULT_APP": _create_default_app_items,
    "WEBSITE_TRAFFIC": _create_website_dashboard,
}

# end of area to be removed


def dashboard_template_from_creation_payload(template: dict[str, Any]) -> DashboardTemplate:
    """Build an unsaved DashboardTemplate from create_from_template_json body.

    The client may send API-shaped objects (e.g. nested ``created_by``). Only fields used for
    dashboard instantiation are passed through; read-only / relation blobs are not unpacked into ``__init__``.
    """
    return DashboardTemplate(
        template_name=template["template_name"],
        dashboard_description=template["dashboard_description"],
        dashboard_filters=template["dashboard_filters"],
        tiles=template["tiles"],
        tags=template.get("tags"),
        variables=template.get("variables"),
        customization=template.get("customization"),
    )


def create_from_template(
    dashboard: Dashboard,
    template: DashboardTemplate,
    user=None,
    *,
    user_access_control: UserAccessControl | None = None,
) -> None:
    from products.dashboards.backend.customization import (  # noqa: PLC0415 — breaks posthog.models import cycle
        normalize_dashboard_customization,
        stored_customization,
        stored_group_key,
    )

    if not dashboard.name or dashboard.name == "":
        dashboard.name = template.template_name
    dashboard.filters = template.dashboard_filters
    dashboard.description = template.dashboard_description or ""
    dashboard.customization = {
        **stored_customization(template.customization),
        **normalize_dashboard_customization(dashboard.customization),
    }

    for template_tag in template.tags or []:
        tag, _ = Tag.objects.get_or_create(
            name=template_tag,
            team_id=dashboard.team_id,
            defaults={"team_id": dashboard.team_id},
        )
        dashboard.tagged_items.create(tag_id=tag.id)
    dashboard.save()

    for template_tile in template.tiles or []:
        tile_type = template_tile.get("type")
        if tile_type == "INSIGHT":
            query = template_tile.get("query", None)
            _create_tile_for_insight(
                dashboard,
                group_key=stored_group_key(template_tile.get("group_key")),
                name=template_tile.get("name"),
                query=query,
                description=template_tile.get("description"),
                color=template_tile.get("color"),
                layouts=template_tile.get("layouts"),
                tags=template_tile.get("tags"),
                user=user,
            )
        elif tile_type == "TEXT":
            _create_tile_for_text(
                dashboard,
                group_key=stored_group_key(template_tile.get("group_key")),
                color=template_tile.get("color"),
                layouts=template_tile.get("layouts"),
                body=template_tile.get("body"),
                agent_context=template_tile.get("agent_context"),
                transparent_background=template_tile.get("transparent_background"),
            )
        elif tile_type == "BUTTON":
            button = {**template_tile, **(template_tile.get("button_tile") or {})}
            _create_tile_for_button(
                dashboard,
                group_key=stored_group_key(template_tile.get("group_key")),
                color=template_tile.get("color"),
                layouts=template_tile.get("layouts"),
                url=button.get("url", ""),
                text=button.get("text", ""),
                placement=button.get("placement", "left"),
                style=button.get("style", "primary"),
                transparent_background=template_tile.get("transparent_background"),
            )
        elif tile_type == "WIDGET":
            _create_tile_for_widget(
                dashboard,
                group_key=stored_group_key(template_tile.get("group_key")),
                widget_type=template_tile.get("widget_type", ""),
                config=template_tile.get("config", {}),
                color=template_tile.get("color"),
                layouts=template_tile.get("layouts"),
                transparent_background=template_tile.get("transparent_background"),
                user=user,
                user_access_control=user_access_control,
            )
        else:
            logger.error("dashboard_templates.creation.unknown_type", template=template)


def _create_tile_for_text(
    dashboard: Dashboard,
    body: str,
    layouts: dict,
    color: Optional[str],
    agent_context: str | None = None,
    transparent_background: Optional[bool] = None,
    *,
    group_key: str | None = None,
) -> None:
    if agent_context is not None and len(agent_context) > MAX_TEXT_TILE_AGENT_CONTEXT_LENGTH:
        raise ValueError(f"Agent context cannot exceed {MAX_TEXT_TILE_AGENT_CONTEXT_LENGTH} characters")

    text = Text.objects.create(
        team=dashboard.team,
        body=body,
        agent_context=agent_context,
    )
    DashboardTile.objects.create(
        text=text,
        dashboard=dashboard,
        team_id=dashboard.team_id,
        group_key=group_key,
        layouts=layouts,
        color=color,
        transparent_background=transparent_background,
    )


def _create_tile_for_button(
    dashboard: Dashboard,
    url: str,
    text: str,
    layouts: dict,
    color: Optional[str],
    placement: str = "left",
    style: str = "primary",
    transparent_background: Optional[bool] = None,
    *,
    group_key: str | None = None,
) -> None:
    button_tile = ButtonTile.objects.create(
        team=dashboard.team,
        url=url,
        text=text,
        placement=placement,
        style=style,
    )
    DashboardTile.objects.create(
        button_tile=button_tile,
        dashboard=dashboard,
        team_id=dashboard.team_id,
        group_key=group_key,
        layouts=layouts,
        color=color,
        transparent_background=transparent_background,
    )


def _create_tile_for_widget(
    dashboard: Dashboard,
    widget_type: str,
    config: dict,
    layouts: dict | None,
    color: Optional[str],
    transparent_background: Optional[bool] = None,
    user=None,
    *,
    user_access_control: UserAccessControl | None = None,
    group_key: str | None = None,
) -> None:
    from products.dashboards.backend.widget_create import (
        prepare_widget_tile_create,  # noqa: PLC0415 — breaks posthog.models import cycle
    )

    normalized_widget_type, validated_config = prepare_widget_tile_create(
        team=dashboard.team,
        widget_type=widget_type,
        config=config,
        user=user,
        user_access_control=user_access_control,
    )
    with team_scope(dashboard.team_id):
        widget = DashboardWidget.objects.create(
            team=dashboard.team,
            widget_type=normalized_widget_type,
            config=validated_config,
            created_by=user,
            last_modified_by=user,
        )
    DashboardTile.objects.create(
        widget=widget,
        dashboard=dashboard,
        team_id=dashboard.team_id,
        group_key=group_key,
        layouts=layouts or {},
        color=color,
        transparent_background=transparent_background,
    )


def _create_tile_for_insight(
    dashboard: Dashboard,
    name: str,
    description: str,
    layouts: dict,
    color: Optional[str],
    query: Optional[dict] = None,
    tags: Optional[list[str]] = None,
    user=None,
    *,
    group_key: str | None = None,
) -> None:
    insight = Insight.objects.create(
        team=dashboard.team,
        name=name,
        description=description,
        is_sample=True,
        query=query,
        created_by=user,
        last_modified_by=user,
    )
    for tag_name in tags or []:
        tag, _ = Tag.objects.get_or_create(
            name=tag_name,
            team_id=dashboard.team_id,
            defaults={"team_id": dashboard.team_id},
        )
        insight.tagged_items.create(tag_id=tag.id)

    DashboardTile.objects.create(
        insight=insight,
        dashboard=dashboard,
        team_id=dashboard.team_id,
        group_key=group_key,
        layouts=layouts,
        color=color,
    )


def create_dashboard_from_template(
    template_key: str,
    dashboard: Dashboard,
    user=None,
    *,
    user_access_control: UserAccessControl | None = None,
) -> None:
    if template_key in DASHBOARD_TEMPLATES:
        return DASHBOARD_TEMPLATES[template_key](dashboard)

    template = DashboardTemplate.objects.filter(
        Q(team_id=dashboard.team_id)
        | Q(scope=DashboardTemplate.Scope.GLOBAL)
        | Q(scope=DashboardTemplate.Scope.ORGANIZATION, team__organization_id=dashboard.team.organization_id),
        template_name=template_key,
    ).first()
    if not template:
        original_template = DashboardTemplate.original_template()
        if template_key == original_template.template_name:
            template = original_template
        else:
            raise AttributeError(f"Invalid template key `{template_key}` provided.")

    create_from_template(dashboard, template, user, user_access_control=user_access_control)


def create_data_ops_dashboard(team, user) -> Dashboard:
    """
    Creates the default data ops overview dashboard for a team.
    Seeded with a starter tile — users can add more to track sync health, row counts, etc.
    """
    dashboard = Dashboard.objects.create(
        name="Data ops overview",
        description="Your data ops overview. Add insights to track sync health, row counts, and anything else you care about.",
        team=team,
        created_by=user,
        creation_mode="template",
    )

    _create_tile_for_insight(
        dashboard,
        name="Events ingested",
        description="",
        query={
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "series": [
                    {
                        "kind": "EventsNode",
                        "math": "total",
                        "name": "All events",
                        "event": None,
                    }
                ],
                "version": 2,
                "interval": "hour",
                "dateRange": {
                    "date_to": None,
                    "date_from": "-24h",
                    "explicitDate": False,
                },
                "trendsFilter": {"display": "BoldNumber"},
                "compareFilter": {"compare": True, "compare_to": "-1w"},
            },
        },
        layouts={
            "sm": {
                "h": 3,
                "w": 2,
                "x": 0,
                "y": 0,
                "minH": 1,
                "minW": 1,
            },
        },
        color=None,
        user=user,
    )

    return dashboard
