# Generated by Django 3.0.7 on 2020-08-03 10:54

from django.db import migrations

from posthog.models import Filter


def forwards_func(apps, schema_editor):
    DashboardItem = apps.get_model("posthog", "DashboardItem")
    items = DashboardItem.objects.filter(filters__isnull=False)
    for item in items:
        if item.filters == {}:
            continue
        item.filters = Filter(data=item.filters).to_dict()
        item.save()


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0072_action_step_url_matching_regex"),
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_func, elidable=True),
    ]
