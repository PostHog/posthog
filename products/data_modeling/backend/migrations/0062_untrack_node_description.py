from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0061_edge_team_dag_index"),
    ]

    operations = [
        untrack_field(
            "node",
            "description",
            database_operations=[
                # Django stops naming the column in INSERTs here, so a NOT NULL column would reject every new node.
                migrations.RunSQL(
                    'ALTER TABLE "posthog_datamodelingnode" ALTER COLUMN "description" DROP NOT NULL;',
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
