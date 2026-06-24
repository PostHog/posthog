# Agent-scoped identity credentials (`binding: 'agent'`): make agent_user_id
# nullable so one credential can be shared by the whole application, and add the
# agent-scoped partial unique — (application_id, provider) WHERE agent_user_id IS
# NULL — for the shared row.
#
# Rolling-deploy safe as a single migration: the original predicate-less
# (agent_user_id, provider) unique from 0007 is KEPT untouched, so the
# per-principal upsert's predicate-less ON CONFLICT keeps matching it on both old
# and new pods (no 42P10 window). NULL agent_user_id rows are distinct in that
# unique index, so the agent-scoped rows it now permits are constrained instead by
# the new partial unique below. Only NEW pods emit the agent-scoped ON CONFLICT,
# and the partial index it targets exists the moment this migration applies.
#
# Non-concurrent index build is acceptable here: agent_identity_credential is a
# new, low-volume table in the dedicated agent_platform product DB.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0009_agentsession_agenttoolapprovalrequest_is_preview"),
    ]

    operations = [
        migrations.AlterField(
            model_name="agentidentitycredential",
            name="agent_user_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="agentidentitycredential",
            constraint=models.UniqueConstraint(
                condition=models.Q(("agent_user_id__isnull", True)),
                fields=("application_id", "provider"),
                name="agent_identity_credential_unique_agent_provider",
            ),
        ),
    ]
