"""
Initial schema for the agent_stack app — fresh-start migration that creates
the authoring tables (AgentApplication, AgentRevision). Replaces the prior
v1 migrations (0001-0003) which created the now-deleted v1 schema.

Runtime tables (sessions, users, sandbox instances) live in a separate
queue DB and are bootstrapped via SCHEMA_SQL in
`services/agent-shared/src/persistence/pg-schema.ts` — they are intentionally
NOT in this migration. Production deploys two distinct Postgres databases.
"""

from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils
import posthog.helpers.encrypted_fields


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("posthog", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentApplication",
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
                ("name", models.CharField(max_length=255)),
                ("slug", models.CharField(max_length=63)),
                ("description", models.TextField(blank=True, default="")),
                (
                    "encrypted_env",
                    posthog.helpers.encrypted_fields.EncryptedTextField(blank=True, null=True),
                ),
                ("archived", models.BooleanField(default=False)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agent_apps",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "agent_application",
            },
        ),
        migrations.CreateModel(
            name="AgentRevision",
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
                    "state",
                    models.CharField(
                        choices=[
                            ("draft", "draft"),
                            ("ready", "ready"),
                            ("live", "live"),
                            ("archived", "archived"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("bundle_uri", models.TextField()),
                ("bundle_sha256", models.CharField(blank=True, max_length=64, null=True)),
                ("spec", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="revisions",
                        to="agent_stack.agentapplication",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "parent_revision",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="children",
                        to="agent_stack.agentrevision",
                    ),
                ),
            ],
            options={
                "db_table": "agent_revision",
                "indexes": [
                    models.Index(fields=["application", "state"], name="agent_revisi_applica_idx"),
                    models.Index(fields=["state", "created_at"], name="agent_revisi_state_c_idx"),
                ],
            },
        ),
        migrations.AddField(
            model_name="agentapplication",
            name="live_revision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="live_for",
                to="agent_stack.agentrevision",
            ),
        ),
        migrations.AddConstraint(
            model_name="agentapplication",
            constraint=models.UniqueConstraint(
                condition=models.Q(("archived", False)),
                fields=("team", "slug"),
                name="agent_stack_application_unique_active_slug",
            ),
        ),
        migrations.AddIndex(
            model_name="agentapplication",
            index=models.Index(fields=["team", "archived"], name="agent_appli_team_id_idx"),
        ),
    ]
