# Generated by Django 4.2.15 on 2024-10-31 15:47

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0503_experimentsavedmetric_experimenttosavedmetric_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="capture_dead_clicks",
            field=models.BooleanField(blank=True, default=False, null=True),
        ),
    ]
