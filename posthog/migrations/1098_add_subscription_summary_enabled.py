from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1097_add_is_pending_deletion_to_organization"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="summary_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
