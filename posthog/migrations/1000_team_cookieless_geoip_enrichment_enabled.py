from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0999_remove_presorted_events_modifier"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="cookieless_geoip_enrichment_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
