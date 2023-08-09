import datetime as dt
import json

from django.core.management.base import BaseCommand, CommandError

from posthog.batch_exports.models import BatchExport
from posthog.batch_exports.service import update_batch_export


class Command(BaseCommand):
    help = "Update one or more PostHog BatchExport"

    def add_arguments(self, parser):
        """Add arguments for update_batch_export command."""
        parser.add_argument("batch_export_id", metavar="<BATCH-EXPORT-ID>", help="The ID of the BatchExport to patch")

        group = parser.add_mutually_exclusive_group()
        group.add_argument("-p", "--patch", help="The patch to apply to the BatchExport")
        group.add_argument("-f", "--filename", help="Path to file containing the patch")

        parser.add_argument(
            "--dry-run", action="store_true", default=False, help="The patch to apply to the BatchExport"
        )

    def handle(self, *args, **options):
        """Execute the update_batch_export command."""
        if options.get("filename", None) is not None:
            with open(options["filename"].strip(), "r") as patch_file:
                patch = json.load(patch_file)
        elif options.get("patch", None) is not None:
            patch = json.loads(options["patch"])
        else:
            # We should never land here as we use a mutually exclusive group.
            raise CommandError("Either --patch or --filename must be passed.")

        batch_export_id = options["batch_export_id"]

        try:
            batch_export = BatchExport.objects.get(pk=batch_export_id)
        except BatchExport.DoesNotExist:
            raise CommandError(f"BatchExport with ID '{batch_export_id}' not found.")

        destination = batch_export.destination
        patch_destination = patch.get("destination", {})
        destination_data = {
            "type": patch_destination.get("type", destination.type),
            "config": {**destination.config, **patch_destination.get("config", {})},
        }

        patch_start_at = patch.get("start_at", None)
        patch_end_at = patch.get("start_at", None)
        update_data = {
            "interval": patch.get("interval", batch_export.interval),
            "name": patch.get("name", batch_export.name),
            "start_at": dt.datetime.fromisoformat(patch_start_at)
            if patch_start_at is not None
            else batch_export.start_at,
            "start_at": dt.datetime.fromisoformat(patch_end_at) if patch_end_at is not None else batch_export.end_at,
            "destination_data": destination_data,
        }

        if options.get("dry_run", False) is True:
            self.stdout.write("This is a dry run, no update will be executed. We are done.")
            return json.dumps(update_data, indent=4, default=str)

        self.stdout.write(f"Will update BatchExport with the following data:")
        self.stdout.write(json.dumps(update_data, indent=4, default=str))

        update_batch_export(
            batch_export=batch_export,
            **update_data,
        )
        self.stdout.write("Done!")

        updated_data = {
            "interval": batch_export.interval,
            "name": batch_export.name,
            "start_at": batch_export.start_at,
            "start_at": batch_export.end_at,
            "destination_data": {
                "type": batch_export.destination.type,
                "config": batch_export.destination.config,
            },
        }

        return json.dumps(updated_data, indent=4, default=str)
