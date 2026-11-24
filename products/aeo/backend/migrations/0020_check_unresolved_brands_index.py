from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("aeo", "0019_check_brands"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="aeocitationcheck",
            index=models.Index(
                condition=models.Q(brands_resolved_at__isnull=True),
                fields=["team_id"],
                name="aeo_check_unresolved_idx",
            ),
        ),
    ]
