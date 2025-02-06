from django.db import migrations


def migrate_show_mean_from_boolean_to_string(apps, schema_editor):
    Insight = apps.get_model("posthog", "Insight")

    # Get all retention insights
    retention_insights = Insight.objects.filter(
        filters__insight="RETENTION", deleted=False, filters__has_key="show_mean"
    ).exclude(
        filters__show_mean__isnull=True,
    )

    for insight in retention_insights.iterator(chunk_size=100):
        if isinstance(insight.filters.get("show_mean"), bool):
            # Convert boolean to string - if True, use 'simple'
            insight.filters["show_mean"] = "simple" if insight.filters["show_mean"] else None
            insight.save()


def reverse_migrate_show_mean_from_string_to_boolean(apps, schema_editor):
    Insight = apps.get_model("posthog", "Insight")

    # Get all retention insights
    retention_insights = Insight.objects.filter(
        filters__insight="RETENTION", deleted=False, filters__has_key="show_mean"
    ).exclude(
        filters__show_mean__isnull=True,
    )

    for insight in retention_insights.iterator(chunk_size=100):
        if isinstance(insight.filters.get("show_mean"), str):
            # Convert string back to boolean - 'simple' and 'weighted' becomes True
            insight.filters["show_mean"] = (
                insight.filters["show_mean"] == "simple" or insight.filters["show_mean"] == "weighted"
            )
            insight.save()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0559_team_api_query_rate_limit"),
    ]

    operations = [
        migrations.RunPython(
            migrate_show_mean_from_boolean_to_string, reverse_migrate_show_mean_from_string_to_boolean
        ),
    ]
