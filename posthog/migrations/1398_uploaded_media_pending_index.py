from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("posthog", "1397_uploaded_media_dimensions_and_archive"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="uploadedmedia",
            index=models.Index(
                condition=models.Q(("pending", True)),
                fields=["created_at"],
                name="uploadedmedia_pending_created",
            ),
        ),
    ]
