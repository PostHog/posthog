# Subject refactor: the proven external identity now lives on the credential
# (agent_identity_credential.subject), not on agent_user. Drop the old
# posthog_user_id column and add the generic subject field. See M6 in
# plan agent-slack-identity-and-credential-linking.md.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0007_agent_identity_linking"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="agentuser",
            name="posthog_user_id",
        ),
        migrations.AddField(
            model_name="agentidentitycredential",
            name="subject",
            field=models.TextField(blank=True, null=True),
        ),
    ]
