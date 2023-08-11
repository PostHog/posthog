import datetime as dt
import json

from django.core.management.base import BaseCommand, CommandError

from posthog.batch_exports.service import backfill_export, create_batch_export
from posthog.models.plugin import PluginConfig
from posthog.temporal.client import sync_connect


class Command(BaseCommand):
    help = "Create a BatchExport from an existing Export app"

    def add_arguments(self, parser):
        """Add arguments to the parser."""
        parser.add_argument(
            "--plugin-config-id", type=int, help="The ID of the PluginConfig to use as a base for the new BatchExport"
        )
        parser.add_argument(
            "--team-id",
            type=int,
            help="The ID of the team that owns the PluginConfig and where to create the BatchExport.",
        )
        parser.add_argument("--name", default=None, help="The name for the new BatchExport.")
        parser.add_argument(
            "--interval",
            type=str,
            default="hour",
            choices=["hour", "day"],
            help="The frequency of the new BatchExport.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Without this flag, nothing will be executed.",
        )
        parser.add_argument(
            "--disable-plugin-config",
            action="store_true",
            default=False,
            help="Disable existing PluginConfig after creating new BatchExport.",
        )
        parser.add_argument(
            "--backfill-batch-export",
            action="store_true",
            default=False,
            help="Backfill the newly created BatchExport with the last period of data.",
        )

    def handle(self, *args, **options):
        """Handle creation of a BatchExport from a given PluginConfig."""
        team_id = options["team_id"]
        plugin_config_id = options["plugin_config_id"]

        try:
            plugin_config = PluginConfig.objects.get(pk=plugin_config_id, team_id=team_id)
        except PluginConfig.DoesNotExist:
            raise CommandError(f"PluginConfig '{plugin_config_id}' does not exist in team '{team_id}'")

        export_type, config = map_plugin_config_to_destination(plugin_config)

        destination_data = {
            "type": export_type,
            "config": {k: v for k, v in config.items() if v is not None},
        }

        interval = options["interval"]
        name = options["name"] if options["name"] is not None else f"{export_type} Export"
        dry_run = options["dry_run"]

        self.stdout.write(f"A BatchExport in Team '{team_id}' will be created with the following configuration:")
        self.stdout.write(f"Name: {name}")
        self.stdout.write(f"Interval: {interval}")
        self.stdout.write(f"Destination: {destination_data}")

        batch_export_data = {
            "team_id": team_id,
            "interval": interval,
            "name": name,
            "destination_data": destination_data,
        }

        if dry_run is True:
            self.stdout.write("No BatchExport will be created as this is a dry run or confirmation check rejected.")
            return json.dumps(batch_export_data, indent=4, default=str)
        else:
            batch_export = create_batch_export(**batch_export_data)
            self.stdout.write(f"Created BatchExport '{name}' with id '{batch_export.id}'")

        if options.get("disable_plugin_config", False) and dry_run is False:
            plugin_config.enabled = False
            plugin_config.save()
            self.stdout.write("Disabled existing PluginConfig.")

        if options.get("backfill_batch_export", False) and dry_run is False:
            client = sync_connect()
            end_at = dt.datetime.utcnow()
            start_at = end_at - (dt.timedelta(hours=1) if interval == "hourly" else dt.timedelta(days=1))
            backfill_export(client, batch_export_id=batch_export.id, start_at=start_at, end_at=end_at)
            self.stdout.write(f"Triggered backfill for BatchExport '{name}'.")

        self.stdout.write("Done!")

        return json.dumps(
            {
                "id": batch_export.id,
                "team_id": batch_export.team.id,
                "interval": batch_export.interval,
                "name": batch_export.name,
                "destination_data": {
                    "type": batch_export.destination.type,
                    "config": batch_export.destination.config,
                },
            },
            indent=4,
            default=str,
        )


def map_plugin_config_to_destination(plugin_config: PluginConfig) -> tuple[str, dict]:
    """Map a PluginConfig model to a destination type and config.

    Args:
        plugin_config: The PluginConfig model from which to extract destination data.

    Returns:
        A tuple with the destination type and config.

    Raises:
        CommandError: On unsupported Plugin.
    """
    plugin = plugin_config.plugin

    if plugin.name == "S3 Export":
        config = {
            "bucket_name": plugin_config.config["s3BucketName"],
            "region": plugin_config.config["awsRegion"],
            "prefix": plugin_config.config.get("prefix", ""),
            "aws_access_key_id": plugin_config.config["awsAccessKey"],
            "aws_secret_access_key": plugin_config.config["awsSecretAccessKey"],
        }
        export_type = "S3"
    elif plugin.name == "Snowflake Export":
        config = {
            "account": plugin_config.config["account"],
            "database": plugin_config.config["database"],
            "warehouse": plugin_config.config["warehouse"],
            "user": plugin_config.config["username"],
            "password": plugin_config.config.get("password", None),
            "schema": plugin_config.config["dbschema"],
            "table_name": plugin_config.config["table"],
            "role": plugin_config.config.get("role", None),
        }
        export_type = "Snowflake"
    else:
        raise CommandError(
            f"Unsupported Plugin: '{plugin.name}'.  Supported Plugins are: 'Snowflake Export' and 'S3 Export'"
        )

    return (export_type, config)
