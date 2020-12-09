# Generated by Django 3.0.11 on 2020-12-08 19:07

from django.db import migrations, models


def forward(apps, schema_editor):
    DashboardItem = apps.get_model("posthog", "DashboardItem")
    # no cases of type AND display being null in production
    for item in DashboardItem.objects.filter(filters__display__isnull=True):
        item.filters["display"] = item.type or "ActionsLineGraph"
        item.save()

    for item in DashboardItem.objects.filter(type__isnull=False, filters__insight__isnull=True):
        if item.type == "FunnelViz":
            item.filters["insight"] = "FUNNELS"
        else:
            item.filters["insight"] = "TRENDS"
        item.save()


def reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0104_auto_20201208_1052"),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
