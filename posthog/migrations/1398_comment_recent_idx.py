from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1397_uploaded_media_dimensions_and_archive"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="comment",
            index=models.Index(
                fields=["team_id", "deleted", "-created_at", "-id"],
                name="posthog_comment_recent_idx",
            ),
        ),
    ]
