from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ai_observability", "0052_offline_evaluation_models"),
    ]

    # These indexes support the database-only composite foreign keys and share their migration-managed lifecycle.
    operations = [
        CreateIndexConcurrently(
            index_name="aio_score_def_owner_uniq",
            table_name="llm_analytics_scoredefinition",
            columns='("id", "team_id")',
            unique=True,
        ),
        CreateIndexConcurrently(
            index_name="aio_score_ver_def_uniq",
            table_name="llm_analytics_scoredefinitionversion",
            columns='("id", "definition_id")',
            unique=True,
        ),
        CreateIndexConcurrently(
            index_name="aio_dataset_rev_owner_uniq",
            table_name="llm_analytics_datasetrevision_v2",
            columns='("id", "team_id")',
            unique=True,
        ),
        CreateIndexConcurrently(
            index_name="aio_dataset_ver_owner_uniq",
            table_name="llm_analytics_datasetitemversion_v2",
            columns='("id", "team_id")',
            unique=True,
        ),
    ]
