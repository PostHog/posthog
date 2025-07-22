# Generated manually for sharing token rotation with expiry

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0799_alter_team_external_data_workspace_id"),
    ]

    operations = [
        # Add the expires_at field for token rotation
        migrations.AddField(
            model_name="sharingconfiguration",
            name="expires_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When this sharing configuration expires (null = active)",
                null=True,
            ),
        ),
        # Update access_token field to have unique=True
        migrations.AlterField(
            model_name="sharingconfiguration",
            name="access_token",
            field=models.CharField(
                blank=True,
                max_length=400,
                null=True,
                unique=True,
            ),
        ),
        # Add index for fast token+expiry lookups
        migrations.AddIndex(
            model_name="sharingconfiguration",
            index=models.Index(fields=["access_token", "expires_at"], name="sharing_token_expiry_idx"),
        ),
    ]
