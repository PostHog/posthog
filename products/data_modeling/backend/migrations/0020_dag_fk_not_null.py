import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0019_drop_old_dag_text_columns"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="node",
                    name="dag",
                    field=models.ForeignKey(
                        db_column="dag_fk_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="data_modeling.dag",
                    ),
                ),
                migrations.AlterField(
                    model_name="edge",
                    name="dag",
                    field=models.ForeignKey(
                        db_column="dag_fk_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="data_modeling.dag",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        # Enforce NOT NULL via CHECK constraint pattern
                        "ALTER TABLE posthog_datamodelingnode"
                        " ADD CONSTRAINT node_dag_fk_id_not_null CHECK (dag_fk_id IS NOT NULL) NOT VALID;"
                        " ALTER TABLE posthog_datamodelingnode VALIDATE CONSTRAINT node_dag_fk_id_not_null;"
                        " ALTER TABLE posthog_datamodelingnode ALTER COLUMN dag_fk_id SET NOT NULL;"
                        " ALTER TABLE posthog_datamodelingnode DROP CONSTRAINT node_dag_fk_id_not_null;"
                        " ALTER TABLE posthog_datamodelingedge"
                        " ADD CONSTRAINT edge_dag_fk_id_not_null CHECK (dag_fk_id IS NOT NULL) NOT VALID;"
                        " ALTER TABLE posthog_datamodelingedge VALIDATE CONSTRAINT edge_dag_fk_id_not_null;"
                        " ALTER TABLE posthog_datamodelingedge ALTER COLUMN dag_fk_id SET NOT NULL;"
                        " ALTER TABLE posthog_datamodelingedge DROP CONSTRAINT edge_dag_fk_id_not_null;"
                        " -- not-null-ignore: ran sanity checks to confirm this is safe"
                    ),
                    reverse_sql=(
                        "ALTER TABLE posthog_datamodelingnode ALTER COLUMN dag_fk_id DROP NOT NULL;"
                        " ALTER TABLE posthog_datamodelingedge ALTER COLUMN dag_fk_id DROP NOT NULL;"
                    ),
                ),
            ],
        ),
    ]
