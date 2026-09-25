from django.db import migrations

# This migration seeds three GLOBAL dashboard templates for the product analytics Home tab
# template picker. The tile JSON is written inline (not sourced from DashboardTemplate helper
# methods) so this migration stays self-contained: it always produces the same rows, regardless
# of how the live template-building code changes later.

HOME_TAB_TEMPLATE_NAMES = ["SaaS product", "E-commerce", "Mobile app"]


def _text_tile(body: str, *, y: int) -> dict:
    return {
        "type": "TEXT",
        "color": None,
        "transparent_background": True,
        "body": body,
        "layouts": {
            "sm": {"h": 2, "w": 12, "x": 0, "y": y, "minH": 1, "minW": 3},
            "xs": {"h": 3, "w": 1, "x": 0, "y": 0, "minH": 1, "minW": 1},
        },
    }


def _bold_number_trends_tile(
    *, name: str, description: str, series: list[dict], date_from: str, x: int, y: int
) -> dict:
    return {
        "name": name,
        "type": "INSIGHT",
        "color": "blue",
        "query": {
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "series": series,
                "interval": "day",
                "dateRange": {"date_from": date_from, "explicitDate": False},
                "properties": [],
                "trendsFilter": {
                    "display": "BoldNumber",
                    "showLegend": False,
                    "yAxisScaleType": "linear",
                    "showValuesOnSeries": False,
                    "smoothingIntervals": 1,
                    "showPercentStackView": False,
                    "aggregationAxisFormat": "numeric",
                    "showAlertThresholdLines": False,
                },
                "breakdownFilter": {"breakdown_type": "event"},
                "filterTestAccounts": False,
            },
        },
        "layouts": {
            "sm": {"h": 3, "w": 4, "x": x, "y": y, "minH": 3, "minW": 3},
            "xs": {"h": 3, "w": 1, "x": 0, "y": 0, "minH": 3, "minW": 1},
        },
        "description": description,
    }


def _visitors_series(pageview_or_screen_event: str) -> list[dict]:
    return [
        {
            "kind": "GroupNode",
            "operator": "OR",
            "nodes": [
                {"kind": "EventsNode", "event": "$pageview", "name": "$pageview"},
                {"kind": "EventsNode", "event": "$screen", "name": "$screen"},
            ],
            "math": "dau",
            "name": pageview_or_screen_event,
        }
    ]


def _sessions_series(event: str) -> list[dict]:
    return [{"kind": "EventsNode", "math": "unique_session", "name": event, "event": event}]


def _funnel_tile(*, name: str, description: str, steps: list[dict], date_from: str, y: int) -> dict:
    return {
        "name": name,
        "type": "INSIGHT",
        "color": "black",
        "query": {
            "kind": "InsightVizNode",
            "source": {
                "kind": "FunnelsQuery",
                "series": steps,
                "interval": "day",
                "dateRange": {"date_from": date_from, "explicitDate": False},
                "properties": [],
                "funnelsFilter": {
                    "layout": "horizontal",
                    "exclusions": [],
                    "funnelVizType": "steps",
                    "funnelOrderType": "ordered",
                    "funnelStepReference": "total",
                    "funnelWindowInterval": 14,
                    "breakdownAttributionType": "first_touch",
                    "funnelWindowIntervalUnit": "day",
                },
                "breakdownFilter": {"breakdown_type": "event"},
                "filterTestAccounts": False,
            },
        },
        "layouts": {
            "sm": {"h": 5, "w": 12, "x": 0, "y": y, "minH": 5, "minW": 3},
            "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 1},
        },
        "description": description,
    }


def _funnel_step(event: str, custom_name: str) -> dict:
    return {"kind": "EventsNode", "name": event, "event": event, "custom_name": custom_name}


def _retention_tile(*, name: str, description: str, target_entity: dict, returning_entity: dict, y: int) -> dict:
    return {
        "name": name,
        "type": "INSIGHT",
        "color": "blue",
        "query": {
            "kind": "InsightVizNode",
            "source": {
                "kind": "RetentionQuery",
                "dateRange": {"date_from": "-7d", "explicitDate": False},
                "properties": [],
                "retentionFilter": {
                    "period": "Week",
                    "targetEntity": target_entity,
                    "retentionType": "retention_first_time",
                    "totalIntervals": 11,
                    "returningEntity": returning_entity,
                },
                "filterTestAccounts": False,
            },
        },
        "layouts": {
            "sm": {"h": 5, "w": 12, "x": 0, "y": y, "minH": 5, "minW": 3},
            "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 1},
        },
        "description": description,
    }


def _saas_product_template() -> dict:
    return {
        "template_name": "SaaS product",
        "dashboard_description": (
            "How people sign up, activate, and stick with your SaaS product. Built from automatically "
            "captured pageviews, so it works on day one — swap in your own signup and activation events "
            "to make it yours."
        ),
        "tiles": [
            _text_tile(
                "# 👋 SaaS starter\n\n"
                "Built from pageviews so it works immediately. Swap in your own signup and activation "
                "events (see the funnel below) to track what matters for your product.",
                y=0,
            ),
            _bold_number_trends_tile(
                name="Visitors (last 30 days)",
                description="Unique visitors in the last 30 days. A quick pulse on your overall reach.",
                series=_visitors_series("Pageview or screen"),
                date_from="-30d",
                x=0,
                y=2,
            ),
            _bold_number_trends_tile(
                name="Sessions (last 7 days)",
                description="Distinct visits in the last 7 days. A session groups everything one person does in a single sitting.",
                series=_sessions_series("$pageview"),
                date_from="-7d",
                x=4,
                y=2,
            ),
            _funnel_tile(
                name="Signup to activation",
                description=(
                    "An example funnel from visit to signup to activation. Replace 'sign_up' and "
                    "'product_activated' with your own event names."
                ),
                steps=[
                    _funnel_step("$pageview", "Visited site"),
                    _funnel_step("sign_up", "Signed up"),
                    _funnel_step("product_activated", "Activated"),
                ],
                date_from="-30d",
                y=5,
            ),
            _retention_tile(
                name="Weekly retention",
                description=(
                    "How many people come back week after week. Swap the target event for your "
                    "activation event to see product retention."
                ),
                target_entity={"id": "$pageview", "type": "events"},
                returning_entity={"id": "$pageview", "type": "events"},
                y=10,
            ),
        ],
    }


def _ecommerce_template() -> dict:
    return {
        "template_name": "E-commerce",
        "dashboard_description": (
            "How shoppers browse, add to cart, and buy. Built from automatically captured pageviews, so "
            "it works on day one — swap in your own product and checkout events to make it yours."
        ),
        "tiles": [
            _text_tile(
                "# 👋 E-commerce starter\n\n"
                "Built from pageviews so it works immediately. Swap in your own product-view and "
                "checkout events (see the funnel below) to track real purchases.",
                y=0,
            ),
            _bold_number_trends_tile(
                name="Visitors (last 30 days)",
                description="Unique visitors in the last 30 days. A quick pulse on your overall reach.",
                series=_visitors_series("Pageview or screen"),
                date_from="-30d",
                x=0,
                y=2,
            ),
            _bold_number_trends_tile(
                name="Sessions (last 7 days)",
                description="Distinct visits in the last 7 days. A session groups everything one person does in a single sitting.",
                series=_sessions_series("$pageview"),
                date_from="-7d",
                x=4,
                y=2,
            ),
            _funnel_tile(
                name="Purchase funnel",
                description=(
                    "An example purchase funnel. Replace 'product_viewed', 'checkout_started' and "
                    "'order_completed' with your own event names."
                ),
                steps=[
                    _funnel_step("$pageview", "Viewed a page"),
                    _funnel_step("product_viewed", "Viewed a product"),
                    _funnel_step("checkout_started", "Started checkout"),
                    _funnel_step("order_completed", "Completed purchase"),
                ],
                date_from="-30d",
                y=5,
            ),
            _retention_tile(
                name="Repeat purchases",
                description=(
                    "Retention based on repeat purchases. Uses the 'order_completed' event from the "
                    "funnel above — rename it to match your checkout event."
                ),
                target_entity={"id": "order_completed", "type": "events"},
                returning_entity={"id": "order_completed", "type": "events"},
                y=10,
            ),
        ],
    }


def _mobile_app_template() -> dict:
    return {
        "template_name": "Mobile app",
        "dashboard_description": (
            "How people open, onboard into, and return to your mobile app. Built from automatically "
            "captured screen views, so it works on day one — swap in your own onboarding events to make "
            "it yours."
        ),
        "tiles": [
            _text_tile(
                "# 👋 Mobile app starter\n\n"
                "Built from screen views so it works immediately. Swap in your own onboarding and "
                "key-action events (see the funnel below) to track real engagement.",
                y=0,
            ),
            _bold_number_trends_tile(
                name="App opens (last 30 days)",
                description="Unique visitors in the last 30 days. A quick pulse on your overall reach.",
                series=_visitors_series("Pageview or screen"),
                date_from="-30d",
                x=0,
                y=2,
            ),
            _bold_number_trends_tile(
                name="Sessions (last 7 days)",
                description="Distinct sessions in the last 7 days. A session groups everything one person does in a single sitting.",
                series=_sessions_series("$screen"),
                date_from="-7d",
                x=4,
                y=2,
            ),
            _funnel_tile(
                name="Onboarding funnel",
                description=(
                    "An example onboarding funnel. Replace 'onboarding_completed' and "
                    "'key_action_taken' with your own event names."
                ),
                steps=[
                    _funnel_step("$screen", "Opened app"),
                    _funnel_step("onboarding_completed", "Completed onboarding"),
                    _funnel_step("key_action_taken", "Took key action"),
                ],
                date_from="-30d",
                y=5,
            ),
            _retention_tile(
                name="Weekly retention",
                description=(
                    "How many people come back week after week. Swap the target event for your "
                    "activation event to see product retention."
                ),
                target_entity={"id": "$screen", "type": "events"},
                returning_entity={"id": "$screen", "type": "events"},
                y=10,
            ),
        ],
    }


def create_home_tab_dashboard_templates(apps, schema_editor):
    DashboardTemplate = apps.get_model("dashboards", "DashboardTemplate")

    for template in (_saas_product_template(), _ecommerce_template(), _mobile_app_template()):
        DashboardTemplate.objects.get_or_create(
            template_name=template["template_name"],
            team=None,
            defaults={
                "dashboard_description": template["dashboard_description"],
                "dashboard_filters": {},
                "tiles": template["tiles"],
                "tags": [],
                "scope": "global",
                "availability_contexts": ["general"],
                "is_featured": False,
            },
        )


def remove_home_tab_dashboard_templates(apps, schema_editor):
    DashboardTemplate = apps.get_model("dashboards", "DashboardTemplate")
    DashboardTemplate.objects.filter(template_name__in=HOME_TAB_TEMPLATE_NAMES, team=None).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0022_teamhometabdashboard"),
    ]

    operations = [
        migrations.RunPython(create_home_tab_dashboard_templates, remove_home_tab_dashboard_templates),
    ]
