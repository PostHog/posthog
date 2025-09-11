from django.db import migrations


def create_starter_template(apps, schema_editor):
    DashboardTemplate = apps.get_model("posthog", "DashboardTemplate")
    DashboardTemplate.objects.create(
        template_name="Product analytics",
        dashboard_description="High-level overview of your product including daily active users, weekly active users, retention, and growth accounting.",
        dashboard_filters={},
        tiles=[
            {
                "name": "Daily active users (DAUs)",
                "type": "INSIGHT",
                "color": "blue",
                "filters": {
                    "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
                    "display": "ActionsLineGraph",
                    "insight": "TRENDS",
                    "interval": "day",
                    "date_from": "-30d",
                },
                "layouts": {
                    "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3},
                },
                "description": "Shows the number of unique users that use your app every day.",
            },
            {
                "name": "Weekly active users (WAUs)",
                "type": "INSIGHT",
                "color": "green",
                "filters": {
                    "events": [
                        {
                            "id": "$pageview",
                            "math": "dau",
                            "type": "events",
                        }
                    ],
                    "display": "ActionsLineGraph",
                    "insight": "TRENDS",
                    "interval": "week",
                    "date_from": "-90d",
                },
                "layouts": {
                    "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3},
                },
                "description": "Shows the number of unique users that use your app every week.",
            },
            {
                "name": "Retention",
                "type": "INSIGHT",
                "color": "blue",
                "filters": {
                    "period": "Week",
                    "insight": "RETENTION",
                    "target_entity": {"id": "$pageview", "type": "events"},
                    "retention_type": "retention_first_time",
                    "returning_entity": {"id": "$pageview", "type": "events"},
                },
                "layouts": {
                    "sm": {"h": 5, "w": 6, "x": 6, "y": 5, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 10, "minH": 5, "minW": 3},
                },
                "description": "Weekly retention of your users.",
            },
            {
                "name": "Growth accounting",
                "type": "INSIGHT",
                "color": "purple",
                "filters": {
                    "events": [{"id": "$pageview", "type": "events"}],
                    "insight": "LIFECYCLE",
                    "interval": "week",
                    "shown_as": "Lifecycle",
                    "date_from": "-30d",
                    "entity_type": "events",
                },
                "layouts": {
                    "sm": {"h": 5, "w": 6, "x": 0, "y": 5, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 15, "minH": 5, "minW": 3},
                },
                "description": "How many of your users are new, returning, resurrecting, or dormant each week.",
            },
            {
                "name": "Referring domain (last 14 days)",
                "type": "INSIGHT",
                "color": "black",
                "filters": {
                    "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
                    "display": "ActionsBarValue",
                    "insight": "TRENDS",
                    "interval": "day",
                    "breakdown": "$referring_domain",
                    "date_from": "-14d",
                    "breakdown_type": "event",
                },
                "layouts": {
                    "sm": {"h": 5, "w": 6, "x": 0, "y": 10, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 20, "minH": 5, "minW": 3},
                },
                "description": "Shows the most common referring domains for your users over the past 14 days.",
            },
            {
                "name": "Pageview funnel, by browser",
                "type": "INSIGHT",
                "color": "green",
                "filters": {
                    "events": [
                        {
                            "id": "$pageview",
                            "type": "events",
                            "order": 0,
                            "custom_name": "First page view",
                        },
                        {
                            "id": "$pageview",
                            "type": "events",
                            "order": 1,
                            "custom_name": "Second page view",
                        },
                        {
                            "id": "$pageview",
                            "type": "events",
                            "order": 2,
                            "custom_name": "Third page view",
                        },
                    ],
                    "layout": "horizontal",
                    "display": "FunnelViz",
                    "insight": "FUNNELS",
                    "interval": "day",
                    "exclusions": [],
                    "breakdown_type": "event",
                    "breakdown": "$browser",
                    "funnel_viz_type": "steps",
                },
                "layouts": {
                    "sm": {"h": 5, "w": 6, "x": 6, "y": 10, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 25, "minH": 5, "minW": 3},
                },
                "description": "This example funnel shows how many of your users have completed 3 page views, broken down by browser.",
            },
        ],
        tags=[],
    )


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0309_team_autocapture_opt_out"),
    ]

    operations = [migrations.RunPython(create_starter_template, reverse_code=migrations.RunPython.noop)]
