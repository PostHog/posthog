from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("data_modeling", "0046_dwsavedquery_team_live_created_idx"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="DataWarehouseModelPath")],
            database_operations=[
                DropForeignKey("posthog_datawarehousemodelpath", column="team_id"),
                DropForeignKey("posthog_datawarehousemodelpath", column="created_by_id"),
                DropForeignKey("posthog_datawarehousemodelpath", column="saved_query_id"),
                DropForeignKey("posthog_datawarehousemodelpath", column="table_id"),
            ],
        ),
    ]
