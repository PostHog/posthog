# Generated by Django 3.2.16 on 2022-11-09 14:10

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0277_recording_playlist_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="customer_id",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
