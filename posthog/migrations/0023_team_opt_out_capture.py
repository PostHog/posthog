# Generated by Django 3.0.3 on 2020-02-18 20:29

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0022_action_deleted"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="opt_out_capture",
            field=models.BooleanField(default=False),
        ),
    ]
