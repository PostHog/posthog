from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1105_alter_oauthapplication_authorization_grant_type"),
        ("notebooks", "0003_add_kernel_timeouts"),
    ]

    operations = [
        migrations.AddField(
            model_name="alertconfiguration",
            name="investigation_agent_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="alertcheck",
            name="investigation_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("pending", "pending"),
                    ("running", "running"),
                    ("done", "done"),
                    ("failed", "failed"),
                    ("skipped", "skipped"),
                ],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="alertcheck",
            name="investigation_notebook",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="+",
                to="notebooks.notebook",
            ),
        ),
        migrations.AddField(
            model_name="alertcheck",
            name="investigation_error",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
