from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("cdp", "0003_hog_function_drafts"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(
                    model_name="hogfunctiontemplate",
                    name="posthog_hog_templat_55950b_idx",
                ),
                migrations.RemoveIndex(
                    model_name="hogfunctiontemplate",
                    name="posthog_hog_created_6a9df3_idx",
                ),
                migrations.AlterField(
                    model_name="hogfunctiontemplate",
                    name="sha",
                    field=models.CharField(max_length=100),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_hog_templat_55950b_idx",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_hog_created_6a9df3_idx",
                    reverse_sql=migrations.RunSQL.noop,
                ),
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
