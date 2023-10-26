# Generated by Django 3.2.5 on 2022-01-31 20:50

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0203_dashboard_permissions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ee", "0006_event_definition_verification"),
    ]

    operations = [
        migrations.CreateModel(
            name="DashboardPrivilege",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "level",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (21, "Everyone in the project can edit"),
                            (37, "Only those invited to this dashboard can edit"),
                        ]
                    ),
                ),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "dashboard",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="privileges",
                        related_query_name="privilege",
                        to="posthog.dashboard",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="explicit_dashboard_privileges",
                        related_query_name="explicit_dashboard_privilege",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="dashboardprivilege",
            constraint=models.UniqueConstraint(
                fields=("dashboard", "user"), name="unique_explicit_dashboard_privilege"
            ),
        ),
    ]
