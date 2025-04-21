from django.db import migrations


def set_revenue_analytics_enabled_false(apps, schema_editor):
    ExternalDataSource = apps.get_model("posthog", "ExternalDataSource")
    for source in ExternalDataSource.objects.iterator():
        source.revenue_analytics_enabled = False
        source.save(update_fields=["revenue_analytics_enabled"])


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0711_externaldatasource_revenue_analytics_enabled"),
    ]

    operations = [
        migrations.RunPython(set_revenue_analytics_enabled_false, reverse_code=migrations.RunPython.noop),
    ]
