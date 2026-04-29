from django.db import migrations


def create_clickhouse_team_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="ClickHouse Team")


def reverse_create_clickhouse_team_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="ClickHouse Team").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1094_oauth_provisioning_fields"),
    ]

    operations = [
        migrations.RunPython(create_clickhouse_team_group, reverse_create_clickhouse_team_group),
    ]
