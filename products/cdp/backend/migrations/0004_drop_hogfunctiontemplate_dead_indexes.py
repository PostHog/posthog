from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("cdp", "0003_hog_function_drafts"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="hogfunctiontemplate",
            name="posthog_hog_templat_55950b_idx",
        ),
        SafeRemoveIndexConcurrently(
            model_name="hogfunctiontemplate",
            name="posthog_hog_created_6a9df3_idx",
        ),
        # `sha` had db_index=True, a field-level index rather than a Meta index,
        # so the state-aware SafeRemoveIndexConcurrently cannot name it. Drop the
        # btree and its varchar `_like` companion through the raw-SQL
        # DropIndexConcurrently helper, and take db_index off the state.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="hogfunctiontemplate",
                    name="sha",
                    field=models.CharField(max_length=100),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="posthog_hogfunctiontemplate_sha_d0be5888",
                    table_name="posthog_hogfunctiontemplate",
                    columns="(sha)",
                ),
                DropIndexConcurrently(
                    index_name="posthog_hogfunctiontemplate_sha_d0be5888_like",
                    table_name="posthog_hogfunctiontemplate",
                    columns="(sha varchar_pattern_ops)",
                ),
            ],
        ),
    ]
