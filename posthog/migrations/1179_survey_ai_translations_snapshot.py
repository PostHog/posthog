from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1178_datadeletionrequest_person_properties"),
    ]

    operations = [
        migrations.AddField(
            model_name="survey",
            name="ai_translations_snapshot",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
