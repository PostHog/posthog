from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0003_backfill_partition_format"),
    ]

    operations = [
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="origin",
            field=models.CharField(
                blank=True,
                choices=[
                    ("data_warehouse", "Data Warehouse"),
                    ("endpoint", "Endpoint"),
                    ("revenue_analytics", "Revenue Analytics"),
                ],
                default=None,
                help_text="Where this SavedQuery is created.",
                null=True,
            ),
        ),
    ]
