# Generated by Django 3.0.7 on 2020-07-14 16:42

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0068_auto_20200629_1322"),
    ]

    operations = [
        migrations.AddField(
            model_name="action",
            name="last_calculated_at",
            field=models.DateTimeField(blank=True, default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="event",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AlterField(
            model_name="user",
            name="toolbar_mode",
            field=models.CharField(
                blank=True,
                choices=[("default", "default"), ("toolbar", "toolbar")],
                default="default",
                max_length=200,
                null=True,
            ),
        ),
    ]
