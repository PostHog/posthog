# Generated by Django 3.0.6 on 2020-11-24 11:39


from django.db import migrations


def forward(apps, schema_editor):
    DashboardItem = apps.get_model("posthog", "DashboardItem")
    for item in DashboardItem.objects.filter(
        filters__insight="RETENTION",
        filters__selectedDate__isnull=False,
        dashboard__isnull=False,
    ):
        item.filters.pop("selectedDate")
        item.save()


def reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0102_dashboarditem_filters_hash"),
    ]

    operations = [
        migrations.RunPython(forward, reverse, elidable=True),
    ]
