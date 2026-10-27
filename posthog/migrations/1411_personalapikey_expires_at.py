from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1410_deletion_run_log"),
    ]

    operations = [
        migrations.AddField(
            model_name="personalapikey",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
