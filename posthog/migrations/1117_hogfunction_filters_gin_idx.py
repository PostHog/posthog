import django.contrib.postgres.indexes
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1116_hogfunction_active_template_idx"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="hogfunction",
                    index=django.contrib.postgres.indexes.GinIndex(
                        fields=["filters"],
                        name="hog_func_filters_gin_idx",
                        condition=models.Q(filters__isnull=False),
                        opclasses=["jsonb_path_ops"],
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS hog_func_filters_gin_idx "
                        "ON posthog_hogfunction USING GIN (filters jsonb_path_ops) "
                        "WHERE filters IS NOT NULL;"
                    ],
                    reverse_sql=["DROP INDEX IF EXISTS hog_func_filters_gin_idx;"],
                ),
            ],
        ),
    ]
