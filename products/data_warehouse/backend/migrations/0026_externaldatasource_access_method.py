from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0025_datawarehousetable_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldatasource",
            name="access_method",
            field=models.CharField(
                choices=[("warehouse", "warehouse"), ("direct", "direct")],
                default="warehouse",
                max_length=32,
            ),
        ),
    ]
