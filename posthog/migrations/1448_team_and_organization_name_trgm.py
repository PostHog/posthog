from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import migrations
from django.db.models.functions import Upper

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds can't run in a transaction.
    atomic = False

    dependencies = [("posthog", "1447_team_updated_at_index")]

    # On UPPER(name) because icontains compiles to UPPER(col) LIKE UPPER(pattern) on Postgres. A concurrent build
    # takes SHARE UPDATE EXCLUSIVE, which blocks no reads or writes on these hot tables. pg_trgm is already
    # installed (migration 0034).
    operations = [
        SafeAddIndexConcurrently(
            model_name="organization",
            index=GinIndex(OpClass(Upper("name"), name="gin_trgm_ops"), name="posthog_org_name_trgm"),
        ),
        SafeAddIndexConcurrently(
            model_name="team",
            index=GinIndex(OpClass(Upper("name"), name="gin_trgm_ops"), name="posthog_team_name_trgm"),
        ),
    ]
