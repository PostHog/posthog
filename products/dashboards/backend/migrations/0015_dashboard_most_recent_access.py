from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0014_backfill_dashboardtemplate_button_tile_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboard",
            name="most_recent_access",
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
    ]
