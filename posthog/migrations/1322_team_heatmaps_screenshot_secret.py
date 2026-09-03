from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1321_add_user_facet_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="heatmaps_screenshot_secret",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
