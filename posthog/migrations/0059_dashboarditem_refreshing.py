# Generated by Django 3.0.7 on 2020-06-15 18:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0058_dashboarditem_last_refresh"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboarditem",
            name="refreshing",
            field=models.BooleanField(default=False),
        ),
    ]
