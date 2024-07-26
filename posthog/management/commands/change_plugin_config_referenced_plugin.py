import time
from django.core.management.base import BaseCommand
from posthog.models import PluginConfig, Plugin


class Command(BaseCommand):
    help = "Set the plugin_id of a given config or set of configs to something else"

    def add_arguments(self, parser):
        parser.add_argument("config_ids", type=str, help="Plugin config ID or list of ID's, separated by commas")
        parser.add_argument("new_plugin_id", type=int, help="New Plugin ID")
        parser.add_argument("--dry-run", type=bool, help="Print information instead of storing it")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        config_ids = options["config_ids"]
        new_plugin_id = options["new_plugin_id"]

        if "," in config_ids:
            config_ids = {int(x) for x in config_ids.split(",")}
        else:
            config_ids = {int(config_ids)}

        new_plugin = Plugin.objects.get(id=new_plugin_id)
        found_configs = PluginConfig.objects.filter(id__in=config_ids)

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
            print(f"Would update {len(config_ids)} rows")  # noqa T201
