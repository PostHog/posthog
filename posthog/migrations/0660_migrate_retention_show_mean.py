from django.db import migrations


def migrate_show_mean_from_boolean_to_string(apps, schema_editor):
    Insight = apps.get_model("posthog", "Insight")

    # Get all retention insights
    retention_insights = Insight.objects.filter(filters__insight="RETENTION", deleted=False).exclude(
        filters__show_mean__isnull=True
    )

    for insight in retention_insights:
        if isinstance(insight.filters.get("show_mean"), bool):
            # Convert boolean to string - if True, use 'simple'
            insight.filters["show_mean"] = "simple" if insight.filters["show_mean"] else None
            insight.save()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0559_team_api_query_rate_limit"),
    ]

    operations = [
        migrations.RunPython(migrate_show_mean_from_boolean_to_string),
    ]
