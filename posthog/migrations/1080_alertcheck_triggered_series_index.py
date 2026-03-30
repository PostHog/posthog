from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1079_event_filter_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="alertcheck",
            name="triggered_series_index",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
