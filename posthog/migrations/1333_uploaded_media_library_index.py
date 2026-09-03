from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("posthog", "1332_uploaded_media_library"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="uploadedmedia",
            index=models.Index(
                condition=models.Q(("pending", False), ("purpose__isnull", False)),
                fields=["team", "purpose", "-created_at"],
                name="uploadedmedia_lib_by_created",
            ),
        ),
    ]
