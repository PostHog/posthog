# Generated by Django 3.2.13 on 2022-06-15 15:28
# Follow-up to 0233_plugin_source_file

import json
from typing import Any, Dict, Optional, cast

from django.db import migrations

from posthog.plugins.utils import get_file_from_archive


def forwards_func(apps, schema_editor):
    Plugin = apps.get_model("posthog", "Plugin")
    PluginSourceFile = apps.get_model("posthog", "PluginSourceFile")
    for plugin in Plugin.objects.exclude(plugin_type="source").exclude(plugin_type="local"):
        # PluginSourceFile.objects.update_or_create_from_plugin_archive() inlined
        plugin_json = cast(Optional[Dict[str, Any]], get_file_from_archive(plugin.archive, "plugin.json"))
        if not plugin_json:
            continue
        PluginSourceFile.objects.create(
            plugin=plugin, filename="plugin.json", source=json.dumps(plugin_json),
        )
        main_filename_defined = plugin_json.get("main")
        main_filenames_to_try = [main_filename_defined] if main_filename_defined else ["index.js", "index.ts"]
        for main_filename in main_filenames_to_try:
            if index_ts := get_file_from_archive(plugin.archive, main_filename, json_parse=False):
                PluginSourceFile.objects.create(
                    plugin=plugin, filename="index.ts", source=index_ts,
                )
                break
        else:
            continue
        if frontend_tsx := get_file_from_archive(plugin.archive, "frontend.tsx", json_parse=False):
            PluginSourceFile.objects.create(
                plugin=plugin, filename="frontend.tsx", source=frontend_tsx,
            )


def reverse_func(apps, schema_editor):
    PluginSourceFile = apps.get_model("posthog", "PluginSourceFile")
    PluginSourceFile.objects.filter(plugin__plugin_type__in=["source", "local"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0242_team_live_events_columns"),
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_func),
    ]
