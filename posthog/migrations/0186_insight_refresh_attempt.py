# Generated by Django 3.2.5 on 2021-11-30 13:10

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0185_special_migrations"),
    ]

    operations = [
        migrations.AddField(
            model_name="insight",
            name="refresh_attempt",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
