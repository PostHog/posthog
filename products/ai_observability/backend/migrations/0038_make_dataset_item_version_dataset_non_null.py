import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0037_backfill_dataset_item_version_dataset"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datasetitemversion",
            name="dataset",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="item_versions",
                to="ai_observability.dataset",
            ),
        ),
    ]
