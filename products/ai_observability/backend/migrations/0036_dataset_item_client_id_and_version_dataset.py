import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0035_evaluation_directory_index"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="datasetitem",
                    name="uniq_llma_dataset_item_v2_ext",
                ),
                migrations.RenameField(
                    model_name="datasetitem",
                    old_name="external_id",
                    new_name="client_item_id",
                ),
                migrations.AlterField(
                    model_name="datasetitem",
                    name="client_item_id",
                    field=models.CharField(blank=True, db_column="external_id", max_length=255, null=True),
                ),
                migrations.AddConstraint(
                    model_name="datasetitem",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(client_item_id__isnull=False),
                        fields=("dataset", "client_item_id"),
                        name="uniq_llma_dataset_item_v2_ext",
                    ),
                ),
            ],
            database_operations=[],
        ),
        migrations.AddField(
            model_name="datasetitemversion",
            name="dataset",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="item_versions",
                to="ai_observability.dataset",
            ),
        ),
    ]
