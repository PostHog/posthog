from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("data_warehouse", "0058_alter_managedwarehousebackfillpartition_team")]

    operations = [
        migrations.AlterField(
            model_name="managedwarehousebackfillpartition",
            name="dataset",
            field=models.CharField(
                choices=[("events", "Events"), ("persons", "Persons"), ("groups", "Groups")], max_length=16
            ),
        ),
    ]
