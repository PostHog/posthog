# Generated by Django 4.2.18 on 2025-03-13 01:13

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0685_add_playlist_counted_date"),
    ]

    operations = [
        migrations.AlterField(
            model_name="errortrackingissue",
            name="status",
            field=models.TextField(
                choices=[
                    ("archived", "Archived"),
                    ("active", "Active"),
                    ("resolved", "Resolved"),
                    ("pending_release", "Pending release"),
                    ("suppressed", "Suppressed"),
                ],
                default="active",
            ),
        ),
    ]
