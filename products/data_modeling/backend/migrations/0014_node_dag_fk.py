import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0013_edge_dag_fk_node_dag_fk"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="node",
                    name="dag_fk",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="data_modeling.dag",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "posthog_datamodelingnode" '
                        'ADD COLUMN "dag_fk_id" uuid NULL '
                        'CONSTRAINT "posthog_datamodeling_dag_fk_id_a152d589_fk_posthog_d" '
                        'REFERENCES "posthog_datamodelingdag"("id") DEFERRABLE INITIALLY DEFERRED;'
                    ),
                    reverse_sql='ALTER TABLE "posthog_datamodelingnode" DROP COLUMN "dag_fk_id";',
                ),
            ],
        ),
    ]
