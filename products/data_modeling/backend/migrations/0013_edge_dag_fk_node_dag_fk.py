import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0012_add_description_to_node"),
    ]

    operations = [
        # Add the FK column without Django's auto-generated index.
        # Index is added concurrently in migration 0014.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="edge",
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
                        'ALTER TABLE "posthog_datamodelingedge" '
                        'ADD COLUMN "dag_fk_id" uuid NULL '
                        'CONSTRAINT "posthog_datamodeling_dag_fk_id_af85451c_fk_posthog_d" '
                        'REFERENCES "posthog_datamodelingdag"("id") DEFERRABLE INITIALLY DEFERRED;'
                    ),
                    reverse_sql='ALTER TABLE "posthog_datamodelingedge" DROP COLUMN "dag_fk_id";',
                ),
            ],
        ),
    ]
