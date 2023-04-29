# Generated by Django 3.1.8 on 2021-05-26 23:18

from django.db import migrations


# Some funnels accidentally had breakdown values which broke displaying them in the old funnel values
# Resetting these as from this migration forward we'll have funnels that _do_ support breakdowns
def remove_breakdowns(apps, schema_editor):
    DashboardItem = apps.get_model("posthog", "DashboardItem")
    for obj in DashboardItem.objects.filter(filters__insight="FUNNELS", filters__breakdown__isnull=False):
        if obj.filters.get("breakdown"):
            del obj.filters["breakdown"]
        if obj.filters.get("breakdown_type"):
            del obj.filters["breakdown_type"]
        obj.save()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0158_new_token_format"),
    ]

    operations = [
        migrations.RunPython(remove_breakdowns, migrations.RunPython.noop, elidable=True),
    ]
