# Generated by Django 3.0.11 on 2020-12-18 09:04

from django.db import migrations

MAPPING = {"h": "Hour", "d": "Day", "w": "Week", "m": "Month"}


def fix_retention_dashboard_items(apps, schema_editor):
    DashboardItem = apps.get_model("posthog", "DashboardItem")
    for item in DashboardItem.objects.filter(filters__insight="RETENTION", filters__period__in=MAPPING.keys()):
        item.filters["period"] = MAPPING[item.filters["period"]]
        item.save()


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0108_plugin_organization"),
    ]

    operations = [
        migrations.RunPython(fix_retention_dashboard_items, backwards),
    ]
