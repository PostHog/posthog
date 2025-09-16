import time

from django.core.management.base import BaseCommand

from posthog.models import Plugin, PluginConfig


class Command(BaseCommand):
    help = "Set the plugin_id of a given config or set of configs to something else"

    def add_arguments(self, parser):
        parser.add_argument(
            "target_ids",
            type=str,
            help="Plugin config (or plugin, in bulk mode) ID or list of ID's, separated by commas",
        )
        parser.add_argument("new_plugin_id", type=int, help="New Plugin ID")
        parser.add_argument("--dry-run", type=bool, help="Print information instead of storing it")
        parser.add_argument(
            "--bulk-mode",
            type=bool,
            help="Switches to running in bulk mode. target_ids is interpreted as a list of plugin ids, and ANY plugin config referencing any of them will be modified to reference the new_plugin_id",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        target_ids = options["target_ids"]
        new_plugin_id = options["new_plugin_id"]
        bulk_mode = options["bulk_mode"]

        if "," in target_ids:
            target_ids = {int(x) for x in target_ids.split(",")}
        else:
            target_ids = {int(target_ids)}

        if bulk_mode:
            print("Running in bulk mode")  # noqa T201
            found_configs = PluginConfig.objects.filter(plugin_id__in=target_ids)
        else:
            print("Running in per-config mode")  # noqa T201
            found_configs = PluginConfig.objects.filter(id__in=target_ids)

        new_plugin = Plugin.objects.get(id=new_plugin_id)

        existing_plugins = [(config.id, Plugin.objects.get(id=config.plugin_id).name) for config in found_configs]

        print(f"Going to update {len(found_configs)} rows, setting plugin_id to {new_plugin_id} ({new_plugin.name})")  # noqa T201
        print(f"Current plugins (config_id, plugin_name) - MAKE SURE THESE MAKE SENSE: {existing_plugins}")  # noqa T201
        print("Sleeping for 10 seconds, now is your chance to cancel")  # noqa T201
        time.sleep(10)
        print("Starting")  # noqa T201
        if not dry_run:
            updated = found_configs.update(plugin=new_plugin)
            print(f"Updated {updated} rows")  # noqa T201
        else:
            print(f"Would update {len(found_configs)} rows")  # noqa T201
