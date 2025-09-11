# Generated manually for sharing token rotation with expiry

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0799_migrate_playlist_types_take_2"),
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
    ]
