from django.db import migrations


def create_starter_template(apps, schema_editor):
    DashboardTemplate = apps.get_model("posthog", "DashboardTemplate")
    DashboardTemplate.objects.create(
        template_name="Flagged Feature Usage",
        dashboard_description="Overview of engagement with the flagged feature including daily active users and weekly active users.",
        dashboard_filters={},
        tiles=[
            {
                "name": "Daily active users (DAUs)",
                "type": "INSIGHT",
                "color": "blue",
                "filters": {
                    "events": ["{ENGAGEMENT}"],
                    "display": "ActionsLineGraph",
                    "insight": "TRENDS",
                    "interval": "day",
                    "date_from": "-30d",
                },
                "layouts": {
                    "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3},
                },
                "description": "Shows the number of unique users that use your feature every day.",
            },
            {
                "name": "Weekly active users (WAUs)",
                "type": "INSIGHT",
                "color": "green",
                "filters": {
                    "events": ["{ENGAGEMENT}"],
                    "display": "ActionsLineGraph",
                    "insight": "TRENDS",
                    "interval": "week",
                    "date_from": "-90d",
                },
                "layouts": {
                    "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3},
                },
                "description": "Shows the number of unique users that use your feature every week.",
            },
        ],
        tags=[],
        variables=[
            {
                "id": "ENGAGEMENT",
                "name": "Engagement",
                "type": "event",
                "default": {"name": "$pageview", "id": "$pageview"},
                "required": True,
                "description": "The event you use to define a user using the new feature",
            }
        ],
        scope="feature_flag",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0327_alter_earlyaccessfeature_stage"),
    ]

    operations = [migrations.RunPython(create_starter_template, reverse_code=migrations.RunPython.noop)]
