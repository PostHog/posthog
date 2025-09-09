import time
import dataclasses

from django.conf import settings
from django.core.management.base import BaseCommand

import structlog

from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.models.hog_functions.hog_function import HogFunctionType
from posthog.plugins.plugin_server_api import get_hog_function_templates

logger = structlog.get_logger(__name__)

TYPES_WITH_JAVASCRIPT_SOURCE = (HogFunctionType.SITE_DESTINATION, HogFunctionType.SITE_APP)

# Templates to include in test mode
TEST_INCLUDE_PYTHON_TEMPLATE_IDS = ["template-slack"]
TEST_INCLUDE_NODEJS_TEMPLATE_IDS = [
    "template-webhook",
    "template-geoip",
    "plugin-posthog-plugin-geoip",
    "plugin-taxonomy-plugin",
]


class Command(BaseCommand):
    help = "Sync HogFunction templates from in-memory and node.js to database"

    def should_include_python_template(self, template):
        """Determine if a Python template should be included based on test mode"""

        if not settings.TEST:
            return True

        return template.type in TYPES_WITH_JAVASCRIPT_SOURCE or template.id in TEST_INCLUDE_PYTHON_TEMPLATE_IDS

    def should_include_nodejs_template(self, template_data):
        """Determine if a Node.js template should be included based on test mode"""

        if not settings.TEST:
            return True

        return template_data.get("id") in TEST_INCLUDE_NODEJS_TEMPLATE_IDS

    def handle(self, *args, **options):
        start_time = time.time()
        total_templates = 0
        updated_count = 0
        error_count = 0
        deleted_count = 0

        self.stdout.write("Starting HogFunction template sync...")

        all_templates: list[dict] = []
        current_template_ids = set()

        # Process templates from HOG_FUNCTION_TEMPLATES (Python templates)
        for template_dc in HOG_FUNCTION_TEMPLATES:
            if not self.should_include_python_template(template_dc):
                continue

            total_templates += 1
            template_dict = dataclasses.asdict(template_dc)
            all_templates.append(template_dict)
            current_template_ids.add(template_dict["id"])

        # Process templates from Node.js
        try:
            response = get_hog_function_templates()
            if response.status_code == 200:
                nodejs_templates_json = response.json()
                for template_data in nodejs_templates_json:
                    if not self.should_include_nodejs_template(template_data):
                        continue

                    all_templates.append(template_data)
                    current_template_ids.add(template_data["id"])
            else:
                self.stdout.write(
                    self.style.WARNING(f"Failed to fetch Node.js templates. Status code: {response.status_code}")
                )
                raise Exception(f"Failed to fetch Node.js templates. Status code: {response.status_code}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error fetching Node.js templates: {str(e)}"))

        for template_data in all_templates:
            try:
                sync_template_to_db(template_data)

                updated_count += 1
            except Exception as e:
                error_count += 1
                logger.error(
                    "Error processing template",
                    template_id=template_data.get("id", "unknown"),
                    error=str(e),
                    exc_info=True,
                )

        try:
            existing_templates = HogFunctionTemplate.objects.values_list("template_id", flat=True).distinct()

            candidates_for_deletion = {
                tid for tid in existing_templates if tid.startswith("coming-soon-")
            } - current_template_ids

            if candidates_for_deletion:
                templates_to_delete = HogFunctionTemplate.objects.filter(template_id__in=candidates_for_deletion)
                deleted_count += templates_to_delete.delete()[0]

                self.stdout.write(
                    self.style.WARNING(
                        f"Deleted {deleted_count} unused templates: {', '.join(candidates_for_deletion)}"
                    )
                )
        except Exception as e:
            logger.error("Error checking for unused templates", error=str(e), exc_info=True)

        # Output summary
        duration = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"Sync completed in {duration:.2f}s. "
                f"Templates: {total_templates}, "
                f"Created or updated: {updated_count}, "
                f"Deleted: {deleted_count}, "
                f"Errors: {error_count}"
            )
        )
