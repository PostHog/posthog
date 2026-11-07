import django.db.models.deletion
import django.contrib.postgres.fields
from django.db import migrations, models

import posthog.uuidt
import posthog.helpers.encrypted_fields


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0021_rule_labels_and_annotations"),
        ("posthog", "1405_user_onboarding_skipped_reason_connector"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlertReceiver",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.uuidt.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=255)),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("slack", "Slack"),
                            ("discord", "Discord"),
                            ("webhook", "Webhook"),
                            ("teams", "Microsoft Teams"),
                            ("pagerduty", "PagerDuty"),
                            ("email", "Email"),
                            ("in_app", "In-app notification"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "config",
                    posthog.helpers.encrypted_fields.EncryptedJSONStringField(default=dict),
                ),
                ("enabled", models.BooleanField(db_default=True, default=True)),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "alerts_platformalertreceiver",
                "constraints": [
                    models.UniqueConstraint(fields=("team", "name"), name="alert_receiver_unique_name"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AlertRoute",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.uuidt.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("matchers", models.JSONField(db_default=[], default=list)),
                (
                    "event_kinds",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=16),
                        default=list,
                        size=None,
                    ),
                ),
                ("position", models.PositiveIntegerField(db_default=0, default=0)),
                ("continue_matching", models.BooleanField(db_default=True, default=True)),
                ("enabled", models.BooleanField(db_default=True, default=True)),
                (
                    "receiver",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="routes",
                        to="alerts_platform.alertreceiver",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "alerts_platformalertroute",
                "indexes": [
                    models.Index(fields=["team", "position"], name="alert_route_team_position_idx"),
                ],
            },
        ),
    ]
