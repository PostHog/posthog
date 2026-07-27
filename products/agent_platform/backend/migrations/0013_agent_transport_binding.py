# Durable transport→canonical-identity binding. Records that a transport
# principal (Slack/Discord/HTTP agent_user) authenticated, via the agent's
# authoritative provider, AS a canonical identity (another agent_user keyed
# identity:<provider>/subject). Resolved at admission so a session only runs
# once a verified identity exists. See docs/identity-and-tools.md.

import django.db.models.manager
import django.db.models.functions.datetime
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0012_agentsession_search_text_turn_count"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentTransportBinding",
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
                ("transport_agent_user_id", models.UUIDField()),
                ("canonical_agent_user_id", models.UUIDField()),
                ("provider", models.TextField()),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now()),
                ),
            ],
            options={
                "db_table": "agent_transport_binding",
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddConstraint(
            model_name="agenttransportbinding",
            constraint=models.UniqueConstraint(
                fields=("application_id", "transport_agent_user_id"),
                name="agent_transport_binding_unique_transport",
            ),
        ),
        migrations.AddIndex(
            model_name="agenttransportbinding",
            index=models.Index(fields=["application_id", "canonical_agent_user_id"], name="atb_canonical_idx"),
        ),
    ]
