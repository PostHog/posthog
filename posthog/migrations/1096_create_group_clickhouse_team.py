from django.contrib.auth.models import Group
from django.db import migrations


def create_clickhouse_team_group(apps, schema_editor):
    Group.objects.get_or_create(name="ClickHouse Team")


def reverse_create_clickhouse_team_group(apps, schema_editor):
    Group.objects.filter(name="ClickHouse Team").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1095_datadeletionrequest_max_timestamp_and_more"),
    ]

    operations = [
        migrations.RunPython(create_clickhouse_team_group, reverse_create_clickhouse_team_group),
    ]
