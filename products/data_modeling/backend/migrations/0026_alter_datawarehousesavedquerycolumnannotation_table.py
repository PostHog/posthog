from django.db import migrations


class Migration(migrations.Migration):
    # Rename the annotation table to the `posthog_...` convention every sibling data_modeling model
    # uses. A plain AlterModelTable is blocked by the migration risk analyzer because renames break old
    # code that still references the old name mid-deploy. That hazard does not apply here: this table
    # was created in 0025 and has no readers or writers yet (no admin, serializer, or API touch it — the
    # only consumers ship in this same change), and it is not a hot table. SeparateDatabaseAndState
    # expresses the verified-safe rename as an explicit, reviewable RunSQL: state_operations keep
    # Django's model state in sync, database_operations do the metadata-only physical rename.
    dependencies = [
        ("data_modeling", "0025_datawarehouse_saved_query_column_annotation"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterModelTable(
                    name="datawarehousesavedquerycolumnannotation",
                    table="posthog_datawarehousesavedquerycolumnannotation",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "data_modeling_datawarehousesavedquerycolumnannotation" '
                        'RENAME TO "posthog_datawarehousesavedquerycolumnannotation";'
                    ),
                    reverse_sql=(
                        'ALTER TABLE "posthog_datawarehousesavedquerycolumnannotation" '
                        'RENAME TO "data_modeling_datawarehousesavedquerycolumnannotation";'
                    ),
                ),
            ],
        ),
    ]
