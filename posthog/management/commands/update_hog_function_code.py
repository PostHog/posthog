from django.core.management.base import BaseCommand

import structlog

from posthog.cdp.validation import compile_hog
from posthog.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Replace a string in the HogFunction code"

    def add_arguments(self, parser):
        parser.add_argument(
            "--replace-key",
            action="replace_key",
            help="The key of the replace option to use",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        replace_key = options.get("replace_key", None)

        if not replace_key:
            self.stdout.write(self.style.ERROR("No replace key provided"))
            return

        replaceOptions = {
            "linked-api-version-update": {
                "template_id": "template-linkedin-ads",
                "from_string": "'LinkedIn-Version': '202409'",
                "to_string": "'LinkedIn-Version': '202508'",
            }
        }

        replaceOption = replaceOptions[replace_key]

        queryset = HogFunction.objects.filter(
            type="destination", deleted=False, template_id=replaceOption["template_id"]
        )

        updated_count = 0
        total_found = len(queryset)

        self.stdout.write(f"Found {total_found} destinations to process")

        for destination in queryset:
            if destination.hog and replaceOption["from_string"] in destination.hog:
                destination.hog = destination.hog.replace(replaceOption["from_string"], replaceOption["to_string"])
                destination.bytecode = compile_hog(destination.hog, destination.type)
                updated_count += 1
                if not dry_run:
                    destination.save(update_fields=["hog", "bytecode"])

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))
            return

        self.stdout.write(self.style.SUCCESS(f"Successfully updated {updated_count} destinations"))
