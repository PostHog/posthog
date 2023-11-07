from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0273_mark_inactive_exports_as_finished"),
    ]

    operations = [
        migrations.AddField(
            model_name="plugin",
            name="icon",
            field=models.CharField(blank=True, max_length=800, null=True),
        ),
    ]
