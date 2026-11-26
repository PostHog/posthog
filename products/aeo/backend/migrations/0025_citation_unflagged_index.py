from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("aeo", "0024_check_citation_first_flags"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="aeocheckcitation",
            index=models.Index(
                condition=models.Q(first_of_domain__isnull=True) | models.Q(first_of_url__isnull=True),
                fields=["team_id", "created_at"],
                name="aeo_citation_unflagged_idx",
            ),
        ),
    ]
