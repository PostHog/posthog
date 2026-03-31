import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1039_subscription_dashboard_export_insights"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="integration",
            field=models.ForeignKey(
                blank=True,
                null=True,
                db_index=False,
                on_delete=django.db.models.deletion.SET_NULL,
                to="posthog.integration",
            ),
        ),
    ]
