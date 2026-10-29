from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1403_project_logo_media_index"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="organization",
            index=models.Index(
                condition=models.Q(("is_active", False)),
                fields=["id"],
                name="org_inactive_id_idx",
            ),
        ),
    ]
