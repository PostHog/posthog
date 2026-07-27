# Subject refactor: the proven external identity now lives on the credential
# (agent_identity_credential.subject), not on agent_user. Drop the field from the
# model and add the generic subject field. See M6 in
# plan agent-slack-identity-and-credential-linking.md.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0007_agent_identity_linking"),
    ]

    operations = [
        # State-only removal of `posthog_user_id`: the model no longer has the
        # field, but we do NOT `DROP COLUMN`. A destructive drop breaks rolling
        # deploys (old code still references it) and can't be rolled back, so the
        # migration safety check blocks it. The column lingers (nullable, unused)
        # until a later migration drops it once this removal has fully deployed.
        # See handbook safe-django-migrations.md "Dropping Columns".
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="agentuser",
                    name="posthog_user_id",
                ),
            ],
            database_operations=[],
        ),
        migrations.AddField(
            model_name="agentidentitycredential",
            name="subject",
            field=models.TextField(blank=True, null=True),
        ),
    ]
