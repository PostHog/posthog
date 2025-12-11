from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0947_insightviewed_null_unique_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="survey", name="scheduled_start_datetime", field=models.DateTimeField(blank=True, null=True)
        ),
        migrations.AddField(
            model_name="survey", name="scheduled_end_datetime", field=models.DateTimeField(blank=True, null=True)
        ),
    ]
