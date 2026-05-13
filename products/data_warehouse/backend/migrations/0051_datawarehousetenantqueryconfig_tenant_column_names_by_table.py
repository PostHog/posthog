from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0050_datawarehousetenantqueryconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="datawarehousetenantqueryconfig",
            name="tenant_column_names_by_table",
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
    ]
