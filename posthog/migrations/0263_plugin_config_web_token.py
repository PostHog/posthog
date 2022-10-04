# Generated by Django 3.2.15 on 2022-09-29 11:07

from django.db import migrations, models

from posthog.models.utils import generate_random_token


def forwards_func(apps, schema_editor):
    PluginConfig = apps.get_model("posthog", "PluginConfig")
    plugin_configs = PluginConfig.objects.all()
    for plugin_config in plugin_configs:
        plugin_config.web_token = generate_random_token()
        plugin_config.save()


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0262_track_viewed_notifications"),
    ]

    operations = [
        migrations.AddField(
            model_name="pluginconfig",
            name="web_token",
            field=models.CharField(default=None, null=True, max_length=64),
        ),
        migrations.AddIndex(
            model_name="pluginconfig",
            index=models.Index(fields=["web_token"], name="posthog_plu_web_tok_ac760a_idx"),
        ),
        migrations.AddIndex(
            model_name="pluginconfig",
            index=models.Index(fields=["enabled"], name="posthog_plu_enabled_f5ed94_idx"),
        ),
        migrations.RunPython(forwards_func, reverse_func),
        migrations.AddField(
            model_name="team",
            name="inject_web_apps",
            field=models.BooleanField(null=True),
        ),
    ]
