from django.db import migrations, models

from posthog.migration_helpers import SafeRemoveIndexConcurrently


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
        # `sha` had db_index=True, which is a field-level index rather than a
        # Meta index, so the helper cannot express it. Drop both the btree and
        # its varchar `_like` companion, and take db_index off the state.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="hogfunctiontemplate",
                    name="sha",
                    field=models.CharField(max_length=100),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_hogfunctiontemplate_sha_d0be5888",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_hogfunctiontemplate_sha_d0be5888_like",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
