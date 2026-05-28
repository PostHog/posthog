from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1186_activitylog_ip_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="survey",
            name="ai_translations_snapshot",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
