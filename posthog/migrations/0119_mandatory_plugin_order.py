# Generated by Django 3.0.6 on 2021-01-28 14:55

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0118_is_demo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pluginconfig",
            name="order",
            field=models.IntegerField(default=0),
            preserve_default=False,
        ),
    ]
