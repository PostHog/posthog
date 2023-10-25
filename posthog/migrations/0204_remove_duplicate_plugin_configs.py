# Generated by Django 3.2.5 on 2021-11-30 08:23
from django.db import migrations


def remove_duplicate_plugin_configs(apps, schema_editor):
    PluginConfig = apps.get_model("posthog", "PluginConfig")
    configs = PluginConfig.objects.raw(
        """
        select * from posthog_pluginconfig ou
        where (
            select count(*) from posthog_pluginconfig inr
            where
                inr.team_id = ou.team_id and
                inr.plugin_id = ou.plugin_id
        ) > 1 order by enabled DESC, id"""
    )
    plugins_kept = []
    for config in configs:
        if config.plugin_id in plugins_kept:
            config.delete()
        else:
            plugins_kept.append(config.plugin_id)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0203_dashboard_permissions"),
    ]

    operations = [
        migrations.RunPython(remove_duplicate_plugin_configs, migrations.RunPython.noop, elidable=True),
    ]
