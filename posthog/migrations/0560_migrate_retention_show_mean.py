from django.db import migrations


def migrate_show_mean_from_boolean_to_string(apps, schema_editor):
    Insight = apps.get_model("posthog", "Insight")

    # Get all retention insights
    retention_insights = Insight.objects.filter(
        deleted=False,
        query__source__kind="RetentionQuery",
        query__source__retentionFilter__has_key="showMean",
    )

    for insight in retention_insights.iterator(chunk_size=100):
        show_mean_value = insight.query["source"]["retentionFilter"]["showMean"]
        if isinstance(show_mean_value, bool):
            # Convert boolean to string - if True, use 'simple' else 'none'
            insight.query["source"]["retentionFilter"]["showMean"] = "simple" if show_mean_value else "none"
            insight.save()


def reverse_migrate_show_mean_from_string_to_boolean(apps, schema_editor):
    Insight = apps.get_model("posthog", "Insight")

    # Get all retention insights
    retention_insights = Insight.objects.filter(
        deleted=False,
        query__source__kind="RetentionQuery",
        query__source__retentionFilter__has_key="showMean",
    )

    for insight in retention_insights.iterator(chunk_size=100):
        show_mean_value = insight.query["source"]["retentionFilter"]["showMean"]
        if isinstance(show_mean_value, str):
            # Convert string back to boolean - 'simple' and 'weighted' becomes True
            insight.query["source"]["retentionFilter"]["showMean"] = (
                show_mean_value == "simple" or show_mean_value == "weighted"
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
