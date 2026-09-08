import time
import dataclasses

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.plugins.plugin_server_api import get_hog_function_templates

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunctionType
from products.warehouse_sources.backend.facade.source_management import (
    SourceRegistry,
    WebhookSource,
    template as default_webhook_template,
)

logger = structlog.get_logger(__name__)

TYPES_WITH_JAVASCRIPT_SOURCE = (HogFunctionType.SITE_DESTINATION, HogFunctionType.SITE_APP)

# Templates to include in test mode
TEST_INCLUDE_PYTHON_TEMPLATE_IDS = [
    "template-warehouse-source-stripe",
    "template-warehouse-source-customer-io",
    "template-warehouse-source-slack",
    "template-warehouse-source-github",
    "template-warehouse-source-default",
]
TEST_INCLUDE_NODEJS_TEMPLATE_IDS = [
    "template-slack",
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

        # Process warehouse source webhook templates from SourceRegistry
        for source in SourceRegistry.get_all_sources().values():
            if not isinstance(source, WebhookSource):
                continue

            wh_template = source.webhook_template
            if wh_template is not None:
                if not self.should_include_python_template(wh_template):
                    continue
                total_templates += 1
                template_dict = dataclasses.asdict(wh_template)
                all_templates.append(template_dict)
                current_template_ids.add(template_dict["id"])

        # Always include the default fallback warehouse webhook template
        if self.should_include_python_template(default_webhook_template):
            total_templates += 1
            default_dict = dataclasses.asdict(default_webhook_template)
            all_templates.append(default_dict)
            current_template_ids.add(default_dict["id"])

        # Process templates from Node.js
        nodejs_error: str | None = None
        try:
            response = get_hog_function_templates()
            if response.status_code != 200:
                raise Exception(f"Failed to fetch Node.js templates. Status code: {response.status_code}")

            for template_data in response.json():
                if not self.should_include_nodejs_template(template_data):
                    continue

                total_templates += 1
                all_templates.append(template_data)
                current_template_ids.add(template_data["id"])
        except Exception as e:
            nodejs_error = str(e)
            self.stdout.write(self.style.ERROR(f"Error fetching Node.js templates: {nodejs_error}"))

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

        # Every coming-soon template comes from the Node.js service. If that fetch failed,
        # current_template_ids holds none of them, and the cleanup below would delete every
        # coming-soon template in the database.
        if nodejs_error:
            self.stdout.write(
                self.style.WARNING("Skipping cleanup of unused templates because the Node.js fetch failed")
            )
        else:
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
        summary = (
            f"Hog function template sync complete in {duration:.2f}s. "
            f"Templates: {total_templates}, "
            f"Created or updated: {updated_count}, "
            f"Deleted: {deleted_count}, "
            f"Errors: {error_count}"
        )
        self.stdout.write(self.style.ERROR(summary) if nodejs_error else self.style.SUCCESS(summary))

        if nodejs_error:
            raise CommandError(f"Node.js templates were not synced: {nodejs_error}")
