# Generated by Django 2.2.7 on 2020-01-30 22:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0014_auto_20200129_0703"),
    ]

    operations = [
        migrations.AddField(
            model_name="actionstep",
            name="event",
            field=models.CharField(blank=True, max_length=400, null=True),
        ),
    ]
