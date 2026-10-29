from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("data_warehouse", "0059_alter_managedwarehousebackfillpartition_dataset")]

    operations = [
        migrations.AddField(
            model_name="teamdatawarehouseconfig",
            name="default_failure_alert_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
