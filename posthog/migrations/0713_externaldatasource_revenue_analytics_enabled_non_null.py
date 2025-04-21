from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0712_set_revenue_analytics_enabled_false"),
    ]

    operations = [
        migrations.AlterField(
            model_name="externaldatasource",
            name="revenue_analytics_enabled",
            field=models.BooleanField(blank=False, null=False, default=False),
        ),
    ]
