from django.db import migrations

from posthog.migration_helpers import DropReindexLeftovers


class Migration(migrations.Migration):
    # DROP INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False
    dependencies = [("ai_observability", "0042_aiobservabilitychecklistitemstate")]

    operations = [
        # An interrupted REINDEX INDEX CONCURRENTLY left an invalid copy of this
        # index on llm_analytics_evaluation. Nothing else can see it, because the
        # copy's name comes from Postgres rather than from a migration.
        DropReindexLeftovers(index_name="llm_analyti_model_c_idx"),
    ]
