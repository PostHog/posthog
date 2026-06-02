from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import AddIndexConcurrently, TrigramExtension
from django.db import migrations, models


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1194_project_updated_at"),
    ]

    operations = [
        # No-op if pg_trgm is already installed (it is, since migration 0034) —
        # kept so the gin_trgm_ops index below is self-contained.
        TrigramExtension(),
        AddIndexConcurrently(
            model_name="cohort",
            index=models.Index(fields=["team", "-created_at"], name="cohort_team_created_idx"),
        ),
        AddIndexConcurrently(
            model_name="cohort",
            index=GinIndex(fields=["name"], name="cohort_name_trgm_idx", opclasses=["gin_trgm_ops"]),
        ),
    ]
