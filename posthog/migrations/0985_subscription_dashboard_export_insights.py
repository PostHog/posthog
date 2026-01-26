from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0984_clear_temporary_tokens"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="dashboard_export_insights",
            field=models.ManyToManyField(
                blank=True,
                related_name="subscriptions_dashboard_export",
                to="posthog.insight",
            ),
        ),
    ]
