# Generated for the session-sleep feature. See docs/session-sleep.md.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0003_agentapplication_global_slug_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentsession",
            name="wake_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agentsession",
            name="slept_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="agentsession",
            index=models.Index(
                condition=models.Q(("wake_at__isnull", False)),
                fields=["state", "wake_at"],
                name="agent_sess_wake_idx",
            ),
        ),
    ]
