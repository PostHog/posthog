# Agent-scoped identity credentials (`binding: 'agent'`): make agent_user_id
# nullable so one credential can be shared by the whole application, and split
# the unique into two partial constraints —
#   - (agent_user_id, provider) WHERE agent_user_id IS NOT NULL  (per-principal)
#   - (application_id, provider) WHERE agent_user_id IS NULL      (agent-scoped)
# Non-concurrent index builds are acceptable here: agent_identity_credential is a
# new, low-volume table in the dedicated agent_platform product DB.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0008_agent_identity_subject"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="agentidentitycredential",
            name="agent_identity_credential_unique_user_provider",
        ),
        migrations.AlterField(
            model_name="agentidentitycredential",
            name="agent_user_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="agentidentitycredential",
            constraint=models.UniqueConstraint(
                condition=models.Q(("agent_user_id__isnull", False)),
                fields=("agent_user_id", "provider"),
                name="agent_identity_credential_unique_user_provider",
            ),
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
