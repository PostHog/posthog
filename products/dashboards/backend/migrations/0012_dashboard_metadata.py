# Generated manually to add provenance metadata to dashboards

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0011_dashboardtile_widget_id_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboard",
            name="metadata",
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
    ]
