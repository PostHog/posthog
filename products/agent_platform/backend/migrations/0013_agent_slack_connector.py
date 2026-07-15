import uuid

import django.db.models.manager
import django.db.models.deletion
import django.contrib.postgres.fields
import django.db.models.functions.datetime
from django.db import migrations, models

import posthog.models.utils
import posthog.helpers.encrypted_fields


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0012_agentsession_search_text_turn_count"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentSlackConnector",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.BigIntegerField(db_index=True)),
                ("slack_workspace_id", models.TextField()),
                (
                    "public_routing_id",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("slack_app_id", models.TextField(blank=True, null=True)),
                ("bot_user_id", models.TextField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "pending"),
                            ("provisioning", "provisioning"),
                            ("install_pending", "install_pending"),
                            ("active", "active"),
                            ("reinstall_required", "reinstall_required"),
                            ("revoked", "revoked"),
                            ("error", "error"),
                        ],
                        db_default="pending",
                        default="pending",
                        max_length=32,
                    ),
                ),
                (
                    "installed_scopes",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), db_default=models.Value("{}"), default=list, size=None
                    ),
                ),
                (
                    "desired_scopes",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), db_default=models.Value("{}"), default=list, size=None
                    ),
                ),
                (
                    "encrypted_credentials",
                    posthog.helpers.encrypted_fields.EncryptedTextField(blank=True, null=True),
                ),
                ("last_error", models.TextField(blank=True, db_default="", default="")),
                ("created_by_id", models.BigIntegerField(blank=True, null=True)),
                ("installed_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_default=django.db.models.functions.datetime.Now(),
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        db_default=django.db.models.functions.datetime.Now(),
                    ),
                ),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="slack_connectors",
                        to="agent_platform.agentapplication",
                    ),
                ),
            ],
            options={
                "db_table": "agent_slack_connector",
                "indexes": [models.Index(fields=["team_id", "status"], name="asc_team_status_idx")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("application", "slack_workspace_id"),
                        name="agent_slack_connector_app_workspace_unique",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("slack_app_id__isnull", False)),
                        fields=("slack_app_id",),
                        name="agent_slack_connector_app_id_unique",
                    ),
                ],
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
    ]
