from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1285_drop_desktop_file_system"),
    ]

    operations = [
        # Nullable, no default: metadata-only ADD COLUMN, no table rewrite.
        migrations.AddField(
            model_name="comment",
            name="idempotency_key",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
