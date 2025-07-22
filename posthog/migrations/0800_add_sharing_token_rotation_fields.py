# Generated manually for sharing token rotation fields

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0799_alter_team_external_data_workspace_id"),
    ]

    operations = [
        # Add the previous_access_token field
        migrations.AddField(
            model_name="sharingconfiguration",
            name="previous_access_token",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Previous access token, valid during grace period",
                max_length=400,
                null=True,
            ),
        ),
        # Add the token_rotated_at field
        migrations.AddField(
            model_name="sharingconfiguration",
            name="token_rotated_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the current token was rotated",
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
    ]
