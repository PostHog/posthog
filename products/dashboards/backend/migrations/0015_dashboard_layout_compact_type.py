from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0014_backfill_dashboardtemplate_button_tile_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboard",
            name="layout_compact_type",
            field=models.CharField(
                choices=[
                    ("vertical", "Vertical"),
                    ("horizontal", "Horizontal"),
                    ("wrap", "Wrap"),
                    ("none", "None"),
                ],
                default="vertical",
                help_text="How dashboard tiles close gaps in the grid layout.",
                max_length=10,
            ),
        ),
    ]
