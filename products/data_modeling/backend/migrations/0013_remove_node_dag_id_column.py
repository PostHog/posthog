from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0012_remove_node_dag_id_and_constraints"),
    ]

    operations = [
        # db column is made nullable and given a default to avoid failures on insert
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="node",
                    name="dag_id",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""ALTER TABLE "posthog_datamodelingnode" ALTER COLUMN "dag_id" SET DEFAULT \'posthog\',
                        ALTER COLUMN "dag_id" DROP NOT NULL;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
