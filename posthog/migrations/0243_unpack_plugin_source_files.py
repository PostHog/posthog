# Generated by Django 3.2.13 on 2022-06-15 15:28

import json
from typing import Any, Dict, Optional, cast

from django.core import exceptions
from django.db import migrations

from posthog.plugins.utils import get_file_from_archive


def forwards_func(apps, schema_editor):
    Plugin = apps.get_model("posthog", "Plugin")
    PluginSourceFile = apps.get_model("posthog", "PluginSourceFile")

    # PluginSourceFile.objects.update_or_create_from_plugin_archive() inlined
    # Only 4 changes:
    # - Plugin and PluginSourceFiles have been stripped from types
    #   (they have to be vars in this scope, but vars cannot be used as types)
    # - plugin_json cannot be provided as an arg
    # - records are `create()`d instead of `update_or_create()`d
    # - there's no return value
    def update_or_create_from_plugin_archive(plugin):
        """Create PluginSourceFile objects from a plugin that has an archive."""
        if plugin.archive is None:
            raise exceptions.ValidationError(
                f"Could not extract files from plugin {plugin.name} ID {plugin.id} - it has no archive"
            )
        # Extract plugin.json - required, can be provided to the function as an optimization
        plugin_json = cast(Optional[Dict[str, Any]], get_file_from_archive(plugin.archive, "plugin.json"))
        if not plugin_json:
            raise exceptions.ValidationError(f"Could not find plugin.json in plugin {plugin.name} ID {plugin.id}")
        # Extract frontend.tsx - optional
        frontend_tsx: Optional[str] = get_file_from_archive(plugin.archive, "frontend.tsx", json_parse=False)
        # Extract index.ts - optional if frontend.tsx is present, otherwise required
        main_filename_defined = plugin_json.get("main")
        main_filenames_to_try = [main_filename_defined] if main_filename_defined else ["index.js", "index.ts"]
        index_ts: Optional[str] = None
        for main_filename in main_filenames_to_try:
            if index_ts := get_file_from_archive(plugin.archive, main_filename, json_parse=False):
                break
        else:
            if frontend_tsx is None:
                raise exceptions.ValidationError(
                    f"Could not find main file {' or '.join(main_filenames_to_try)} in plugin {plugin.name} ID {plugin.id}"
                )
        # Save plugin.json
        PluginSourceFile.objects.create(plugin=plugin, filename="plugin.json", source=json.dumps(plugin_json))
        # Save frontend.tsx
        if frontend_tsx:
            PluginSourceFile.objects.create(plugin=plugin, filename="frontend.tsx", source=frontend_tsx)
        # Save index.ts
        if index_ts:
            # The original name of the file is not preserved, but this greatly simplifies the rest of the code,
            # and we don't need to model the whole filesystem (at this point)
            PluginSourceFile.objects.create(plugin=plugin, filename="index.ts", source=index_ts)

    # Source plugins have already been migrated in 0233_plugin_source_file, while local ones don't store code in the DB
    for plugin in Plugin.objects.exclude(plugin_type="source").exclude(plugin_type="local"):
        update_or_create_from_plugin_archive(plugin)


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
