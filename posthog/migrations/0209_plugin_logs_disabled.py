# Generated by Django 3.2.5 on 2022-02-09 12:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0208_alter_plugin_updated_at"),
    ]

    operations = [
        migrations.AddField(model_name="plugin", name="log_level", field=models.IntegerField(blank=True, null=True),),
    ]
