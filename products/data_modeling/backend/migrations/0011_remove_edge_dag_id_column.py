from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0010_remove_edge_unique_within_dag_and_more"),
    ]

    operations = [
        # db column is made nullable and given a default to avoid failures on insert
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="edge",
                    name="dag_id",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_datamodelingedge" ALTER COLUMN "dag_id" SET DEFAULT \'posthog\',
                            ALTER COLUMN "dag_id" DROP NOT NULL;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
