from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0014_backfill_dashboardtemplate_button_tile_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboard",
            name="tile_gap",
            field=models.PositiveSmallIntegerField(db_default=16, default=16),
        ),
    ]
