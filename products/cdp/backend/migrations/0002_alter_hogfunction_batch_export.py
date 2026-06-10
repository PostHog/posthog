import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("batch_exports", "0002_batchexport_batchexportbackfill_and_more"),
        ("cdp", "0001_migrate_cdp_models"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="hogfunction",
                    name="batch_export",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="batch_exports.batchexport",
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
