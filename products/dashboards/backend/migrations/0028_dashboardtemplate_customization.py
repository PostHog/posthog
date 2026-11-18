from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0027_untrack_dashboard_restriction_level"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboardtemplate",
            name="customization",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
