from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0029_team_data_warehouse_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="description",
            field=models.CharField(blank=True, max_length=1000, null=True),
        ),
    ]
