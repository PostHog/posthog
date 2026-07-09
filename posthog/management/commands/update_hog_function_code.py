import time
from typing import TypedDict

from django.core.management.base import BaseCommand
from django.core.paginator import Paginator

import structlog

from posthog.cdp.validation import compile_hog

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)


class _Replacement(TypedDict):
    from_string: str
    to_string: str


class _ReplaceOption(TypedDict):
    template_id: str
    replacements: list[_Replacement]


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

        replaceOptions: dict[str, _ReplaceOption] = {
            "linked-api-version-update": {
                "template_id": "template-linkedin-ads",
                "replacements": [
                    {
                        "from_string": "'LinkedIn-Version': '202409'",
                        "to_string": "'LinkedIn-Version': '202508'",
                    },
                ],
            },
            "meta-ads-api-version-update": {
                "template_id": "template-meta-ads",
                "replacements": [
                    {
                        "from_string": "graph.facebook.com/v21.0/",
                        "to_string": "graph.facebook.com/v25.0/",
                    },
                ],
            },
            # Microsoft migrated Teams/Power Automate HTTP triggers to environment.api.powerplatform.com.
            # The current template accepts that host, but functions created earlier keep their frozen code
            # and reject the new URL. These swap the stale validation block for the current one: the
            # standard 4-branch and the powerplatform.com:443 variant share the same tail, and the
            # original single-branch (logic.azure.com only) block is replaced whole.
            "microsoft-teams-powerplatform-url": {
                "template_id": "template-microsoft-teams",
                "replacements": [
                    {
                        "from_string": "not match(inputs.webhookUrl, '^https://[^/]+.flow.microsoft.com/[^/]+')) {\n    throw Error('Invalid URL. The URL should match either Azure Logic Apps format (https://<region>.logic.azure.com:443/workflows/...), Power Platform format (https://<tenant>.webhook.office.com/webhookb2/...), or Power Automate format (https://<region>.powerautomate.com/... or https://<region>.flow.microsoft.com/...)')",
                        "to_string": "not match(inputs.webhookUrl, '^https://[^/]+.flow.microsoft.com/[^/]+') and\n    not match(inputs.webhookUrl, '^https://[^/]+.environment.api.powerplatform.com(:443)?/powerautomate/automations/direct/(.*/)?workflows/.*')) {\n    throw Error('Invalid URL. The URL should match either Azure Logic Apps format (https://<region>.logic.azure.com:443/workflows/...), Power Platform format (https://<tenant>.webhook.office.com/webhookb2/...), Power Automate format (https://<region>.powerautomate.com/... or https://<region>.flow.microsoft.com/...), or Power Platform environment format (https://<tenant>.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/...)')",
                    },
                    {
                        "from_string": "if (not match(inputs.webhookUrl, '^https://[^/]+.logic.azure.com:443/workflows/[^/]+/triggers/manual/paths/invoke?.*')) {\n    throw Error('Invalid URL. The URL should match the format: https://<region>.logic.azure.com:443/workflows/<workflowId>/triggers/manual/paths/invoke?...')\n}",
                        "to_string": "if (not match(inputs.webhookUrl, '^https://[^/]+.logic.azure.com:443/workflows/[^/]+/triggers/manual/paths/invoke?.*') and\n    not match(inputs.webhookUrl, '^https://[^/]+.webhook.office.com/webhookb2/[^/]+/IncomingWebhook/[^/]+/[^/]+') and\n    not match(inputs.webhookUrl, '^https://[^/]+.powerautomate.com/[^/]+') and\n    not match(inputs.webhookUrl, '^https://[^/]+.flow.microsoft.com/[^/]+') and\n    not match(inputs.webhookUrl, '^https://[^/]+.environment.api.powerplatform.com(:443)?/powerautomate/automations/direct/(.*/)?workflows/.*')) {\n    throw Error('Invalid URL. The URL should match either Azure Logic Apps format (https://<region>.logic.azure.com:443/workflows/...), Power Platform format (https://<tenant>.webhook.office.com/webhookb2/...), Power Automate format (https://<region>.powerautomate.com/... or https://<region>.flow.microsoft.com/...), or Power Platform environment format (https://<tenant>.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/...)')\n}",
                    },
                ],
            },
            # Real Power Platform environment webhook URLs carry an extra cluster segment (e.g.
            # `/cu/11`) between `.../automations/direct/` and `/workflows/`, so the original
            # `direct/workflows/` regex rejected valid URLs. Widen the path to allow those segments
            # on functions already deployed with the stale pattern.
            "microsoft-teams-powerplatform-cu-path": {
                "template_id": "template-microsoft-teams",
                "replacements": [
                    {
                        "from_string": "automations/direct/workflows/.*')",
                        "to_string": "automations/direct/(.*/)?workflows/.*')",
                    },
                ],
            },
        }

        if not replace_key or replace_key not in replaceOptions:
            self.stdout.write(self.style.ERROR(f"Invalid replace key provided: {replace_key}"))
            return

        replaceOption = replaceOptions[replace_key]

        queryset = HogFunction.objects.filter(
            type="destination", deleted=False, template_id=replaceOption["template_id"]
        )

        updated_count = 0
        failed: list[tuple[str, int, bool, str]] = []
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
                if not destination.hog:
                    continue

                new_hog = destination.hog
                for replacement in replaceOption["replacements"]:
                    if replacement["from_string"] in new_hog:
                        new_hog = new_hog.replace(replacement["from_string"], replacement["to_string"])

                if new_hog == destination.hog:
                    continue

                # A single destination with uncompilable (e.g. hand-edited) hog must not abort the whole run.
                try:
                    new_bytecode = compile_hog(new_hog, destination.type)
                except Exception as e:
                    failed.append((str(destination.id), destination.team_id, destination.enabled, str(e)))
                    continue

                updated_count += 1
                if not dry_run:
                    destination.hog = new_hog
                    destination.bytecode = new_bytecode
                    destination.save(update_fields=["hog", "bytecode"])

        # Output summary
        duration = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"Update completed in {duration:.2f}s. Found: {total_found}, Updated: {updated_count}, Failed: {len(failed)}"
            )
        )

        if failed:
            self.stdout.write(self.style.WARNING(f"{len(failed)} destination(s) failed to compile and were skipped:"))
            for fn_id, team_id, enabled, error in failed:
                self.stdout.write(f"  id={fn_id} team={team_id} enabled={enabled} error={error}")
