# Generated by Django 2.2.7 on 2020-02-01 22:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0015_actionstep_event"),
    ]

    operations = [
        migrations.AddField(
            model_name="user", name="temporary_token", field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
