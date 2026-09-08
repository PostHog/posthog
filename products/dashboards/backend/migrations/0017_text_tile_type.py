from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0016_dashboardsavedview")]

    operations = [
        migrations.AddField(
            model_name="text",
            name="tile_type",
            field=models.CharField(
                db_default="text",
                default="text",
                max_length=64,
            ),
        )
    ]
