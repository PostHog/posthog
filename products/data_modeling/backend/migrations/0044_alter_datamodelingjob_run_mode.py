from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("data_modeling", "0043_datawarehousesavedquery_snapshot")]

    operations = [
        migrations.AlterField(
            model_name="datamodelingjob",
            name="run_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("full_refresh", "Full refresh"),
                    ("incremental", "Incremental"),
                    ("snapshot", "Snapshot"),
                ],
                max_length=20,
                null=True,
            ),
        )
    ]
