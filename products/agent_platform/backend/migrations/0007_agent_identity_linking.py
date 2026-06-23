# Per-principal identity linking: a persistent encrypted credential store keyed
# by (agent_user, provider), plus a single-use signed-state row for in-flight
# OAuth link round-trips. See plan agent-slack-identity-and-credential-linking.md.

import django.db.models.manager
import django.contrib.postgres.fields
import django.db.models.functions.datetime
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0006_remove_agentapplication_encrypted_env"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentIdentityCredential",
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
                ("application_id", models.UUIDField()),
                ("agent_user_id", models.UUIDField()),
                ("provider", models.TextField()),
                ("encrypted_credentials", models.TextField()),
                (
                    "scopes",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), db_default=models.Value("{}"), default=list, size=None
                    ),
                ),
                ("state", models.TextField(db_default="active", default="active")),
                ("access_expires_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now()),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now()),
                ),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "agent_identity_credential",
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.CreateModel(
            name="AgentIdentityLinkState",
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
                ("application_id", models.UUIDField()),
                ("agent_user_id", models.UUIDField()),
                ("provider", models.TextField()),
                (
                    "scopes",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), db_default=models.Value("{}"), default=list, size=None
                    ),
                ),
                ("code_verifier", models.TextField()),
                ("redirect_uri", models.TextField()),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now()),
                ),
            ],
            options={
                "db_table": "agent_identity_link_state",
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddConstraint(
            model_name="agentidentitycredential",
            constraint=models.UniqueConstraint(
                fields=("agent_user_id", "provider"),
                name="agent_identity_credential_unique_user_provider",
            ),
        ),
        migrations.AddIndex(
            model_name="agentidentitycredential",
            index=models.Index(fields=["application_id"], name="aic_application_idx"),
        ),
        migrations.AddIndex(
            model_name="agentidentitylinkstate",
            index=models.Index(fields=["expires_at"], name="ails_expires_idx"),
        ),
    ]
