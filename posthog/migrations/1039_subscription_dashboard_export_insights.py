from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1038_experiment_status_backfill"),
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
