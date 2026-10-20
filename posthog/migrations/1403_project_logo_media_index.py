from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1402_project_logo_media"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="project",
            index=models.Index(
                condition=models.Q(("logo_media__isnull", False)),
                fields=["logo_media"],
                name="posthog_project_logo_media_idx",
            ),
        ),
    ]
