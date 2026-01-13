import time

from django.core.management.base import BaseCommand
from django.core.paginator import Paginator

import structlog

from posthog.cdp.validation import compile_hog
from posthog.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Replace a string in the HogFunction code"

    def add_arguments(self, parser):
        parser.add_argument(
            "--replace-key",
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
        start_time = time.time()

        replaceOptions = {
            "linked-api-version-update": {
                "template_id": "template-linkedin-ads",
                "from_string": "'LinkedIn-Version': '202409'",
                "to_string": "'LinkedIn-Version': '202508'",
            }
        }

        if not replace_key or replace_key not in replaceOptions:
            self.stdout.write(self.style.ERROR(f"Invalid replace key provided: {replace_key}"))
            return

        replaceOption = replaceOptions[replace_key]

        queryset = HogFunction.objects.filter(
            type="destination", deleted=False, template_id=replaceOption["template_id"]
        )

        updated_count = 0
        total_found = queryset.count()
        paginator = Paginator(queryset.order_by("id"), 1000)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))

        self.stdout.write(f"Found {total_found} destinations to process")

        for page_num in paginator.page_range:
            page = paginator.page(page_num)

            self.stdout.write(
                f"Processing page {page_num}/{paginator.num_pages} ({len(page.object_list)} destinations)..."
            )

            for destination in page.object_list:
                if destination.hog and replaceOption["from_string"] in destination.hog:
                    destination.hog = destination.hog.replace(replaceOption["from_string"], replaceOption["to_string"])
                    destination.bytecode = compile_hog(destination.hog, destination.type)
                    updated_count += 1
                    if not dry_run:
                        destination.save(update_fields=["hog", "bytecode"])

        # Output summary
        duration = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"Update completed in {duration:.2f}s. " f"Found: {total_found}, " f"Updated: {updated_count}, "
            )
        )
