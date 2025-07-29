import dataclasses
from django.core.management.base import BaseCommand
import structlog
import time
from django.conf import settings
from posthog.cdp.templates import HOG_FUNCTION_TEMPLATES
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.plugins.plugin_server_api import get_hog_function_templates
from posthog.models.hog_functions.hog_function import HogFunctionType

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

        self.stdout.write("Starting HogFunction template sync...")

        all_templates: list[dict] = []

        # Process templates from HOG_FUNCTION_TEMPLATES (Python templates)
        for template_dc in HOG_FUNCTION_TEMPLATES:
            if not self.should_include_python_template(template_dc):
                continue

            total_templates += 1
            all_templates.append(dataclasses.asdict(template_dc))

        # Process templates from Node.js
        try:
            response = get_hog_function_templates()
            if response.status_code == 200:
                nodejs_templates_json = response.json()
                for template_data in nodejs_templates_json:
                    if not self.should_include_nodejs_template(template_data):
                        continue

                    all_templates.append(template_data)
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

        # Output summary
        duration = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"Sync completed in {duration:.2f}s. "
                f"Templates: {total_templates}, "
                f"Created or updated: {updated_count}, "
                f"Errors: {error_count}"
            )
        )


# python manage.py shell
# from posthog.models.hog_function_template import HogFunctionTemplate
# templates = HogFunctionTemplate.objects.filter(sha="")
# print(templates.count())
# templates.delete()
