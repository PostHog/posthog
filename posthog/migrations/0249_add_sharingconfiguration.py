# Generated by Django 3.2.13 on 2022-06-29 12:03

import django.db.models.deletion
from django.db import migrations, models

import posthog.models.sharing_configuration


def create_sharing_configurations(apps, _) -> None:
    Dashboard = apps.get_model("posthog", "Dashboard")
    SharingConfiguration = apps.get_model("posthog", "SharingConfiguration")
    dashboards = Dashboard.objects.filter(is_shared=True).values("id", "team_id", "is_shared", "share_token").all()

    batch_size = 1_000
    sharing_configurations = [
        SharingConfiguration(
            team_id=dashboard["team_id"],
            dashboard_id=dashboard["id"],
            enabled=dashboard["is_shared"],
            access_token=dashboard["share_token"],
        )
        for dashboard in dashboards
    ]
    SharingConfiguration.objects.bulk_create(sharing_configurations, batch_size=batch_size)


def reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0248_add_context_for_csv_exports"),
    ]

    operations = [
        migrations.CreateModel(
            name="SharingConfiguration",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("enabled", models.BooleanField(default=False)),
                (
                    "access_token",
                    models.CharField(
                        blank=True,
                        default=posthog.models.sharing_configuration.get_default_access_token,
                        max_length=400,
                        null=True,
                        unique=True,
                    ),
                ),
                (
                    "dashboard",
                    models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="posthog.dashboard"),
                ),
                (
                    "insight",
                    models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="posthog.insight"),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
        ),
        migrations.RunPython(create_sharing_configurations, reverse),
    ]
