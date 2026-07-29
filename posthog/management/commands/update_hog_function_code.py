import time
from typing import NotRequired, TypedDict

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
    type: NotRequired[str]


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
            # Google Ads API v21 sunsets 2026-08-05 (VERSION_SUNSET). Bump the pinned version in
            # existing destinations to v24 (current major, sunsets ~2027-05). Covers the whole stale
            # range v18-v23 since destinations carry whatever version the template pinned when created;
            # only one matches per destination, and a v24 no-op is skipped.
            "google-ads-api-version-update": {
                "template_id": "template-google-ads",
                "replacements": [
                    {"from_string": f"googleads.googleapis.com/v{v}/", "to_string": "googleads.googleapis.com/v24/"}
                    for v in range(18, 24)
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
                        "to_string": "not match(inputs.webhookUrl, '^https://[^/]+.flow.microsoft.com/[^/]+') and\n    not match(inputs.webhookUrl, '^https://[^/]+.environment.api.powerplatform.com(:443)?/powerautomate/automations/direct/(.*/)?workflows/.*')) {\n    throw Error('Invalid URL. The URL should match either Azure Logic Apps format (https://<region>.logic.azure.com:443/workflows/...), Power Platform format (https://<tenant>.webhook.office.com/webhookb2/...), Power Automate format (https://<region>.powerautomate.com/... or https://<region>.flow.microsoft.com/...), or Power Platform environment format (https://<tenant>.environment.api.powerplatform.com:443/powerautomate/automations/direct/[<cluster>/]workflows/...)')",
                    },
                    {
                        "from_string": "if (not match(inputs.webhookUrl, '^https://[^/]+.logic.azure.com:443/workflows/[^/]+/triggers/manual/paths/invoke?.*')) {\n    throw Error('Invalid URL. The URL should match the format: https://<region>.logic.azure.com:443/workflows/<workflowId>/triggers/manual/paths/invoke?...')\n}",
                        "to_string": "if (not match(inputs.webhookUrl, '^https://[^/]+.logic.azure.com:443/workflows/[^/]+/triggers/manual/paths/invoke?.*') and\n    not match(inputs.webhookUrl, '^https://[^/]+.webhook.office.com/webhookb2/[^/]+/IncomingWebhook/[^/]+/[^/]+') and\n    not match(inputs.webhookUrl, '^https://[^/]+.powerautomate.com/[^/]+') and\n    not match(inputs.webhookUrl, '^https://[^/]+.flow.microsoft.com/[^/]+') and\n    not match(inputs.webhookUrl, '^https://[^/]+.environment.api.powerplatform.com(:443)?/powerautomate/automations/direct/(.*/)?workflows/.*')) {\n    throw Error('Invalid URL. The URL should match either Azure Logic Apps format (https://<region>.logic.azure.com:443/workflows/...), Power Platform format (https://<tenant>.webhook.office.com/webhookb2/...), Power Automate format (https://<region>.powerautomate.com/... or https://<region>.flow.microsoft.com/...), or Power Platform environment format (https://<tenant>.environment.api.powerplatform.com:443/powerautomate/automations/direct/[<cluster>/]workflows/...)')\n}",
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
                    {
                        "from_string": "automations/direct/workflows/...)')",
                        "to_string": "automations/direct/[<cluster>/]workflows/...)')",
                    },
                ],
            },
            # The curated-list bypass for non-browser $lib was applied to the user agent check as
            # well as the IP check, so a server-side event that forwards the end user's UA never
            # gets filtered. Only the IP half of that bypass is warranted; move existing
            # transformations onto the split gate. Matches only functions created with the bypass,
            # which are exactly the affected ones.
            "bot-detection-forwarded-user-agent": {
                "template_id": "template-bot-detection",
                "type": "transformation",
                "replacements": [
                    {
                        "from_string": "// PostHog's curated bot UA and IP lists are tuned for browser traffic. Server-side\n// SDKs (posthog-python, posthog-node, ...) send HTTP-client UAs like 'python-httpx'\n// and backend IPs that match those lists but are not bots. Treat anything other than\n// the browser SDKs ($lib in {web, js}) as non-browser and skip the curated checks.\n// Customer-configured customBotPatterns and customIpPrefixes still apply regardless.",
                        "to_string": "// PostHog's curated bot lists are tuned for browser traffic, so the two halves of this\n// function trust them differently for a server-side SDK (posthog-python, posthog-node, ...).\n// $ip is always stamped from the connecting host, so there it is the customer's backend\n// egressing from a datacenter range that the curated list reads as a bot: only the browser\n// SDKs ($lib in {web, js}) and events with no $lib get the curated IP check. The user agent\n// property is the opposite. Ingestion never stamps it and no server SDK sends its own\n// HTTP-client UA there, so a server-side event that carries one has the end user's UA\n// forwarded deliberately, and it gets the curated UA check whatever $lib says.\n// Customer-configured customBotPatterns and customIpPrefixes still apply regardless.",
                    },
                    {
                        "from_string": "if (is_browser_traffic and inputs.filterKnownBotUserAgents and isKnownBotUserAgent(user_agent)) {",
                        "to_string": "if (inputs.filterKnownBotUserAgents and isKnownBotUserAgent(user_agent)) {",
                    },
                ],
            },
        }

        if not replace_key or replace_key not in replaceOptions:
            self.stdout.write(self.style.ERROR(f"Invalid replace key provided: {replace_key}"))
            return

        replaceOption = replaceOptions[replace_key]

        queryset = HogFunction.objects.filter(
            type=replaceOption.get("type", "destination"), deleted=False, template_id=replaceOption["template_id"]
        )

        updated_count = 0
        failed: list[tuple[str, int, bool, str]] = []
        total_found = queryset.count()
        paginator = Paginator(queryset.order_by("id"), 1000)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))

        self.stdout.write(f"Found {total_found} hog functions to process")

        for page_num in paginator.page_range:
            page = paginator.page(page_num)

            self.stdout.write(
                f"Processing page {page_num}/{paginator.num_pages} ({len(page.object_list)} hog functions)..."
            )

            for hog_function in page.object_list:
                if not hog_function.hog:
                    continue

                new_hog = hog_function.hog
                for replacement in replaceOption["replacements"]:
                    if replacement["from_string"] in new_hog:
                        new_hog = new_hog.replace(replacement["from_string"], replacement["to_string"])

                if new_hog == hog_function.hog:
                    continue

                # A single function with uncompilable (e.g. hand-edited) hog must not abort the whole run.
                try:
                    new_bytecode = compile_hog(new_hog, hog_function.type)
                except Exception as e:
                    failed.append((str(hog_function.id), hog_function.team_id, hog_function.enabled, str(e)))
                    continue

                updated_count += 1
                if not dry_run:
                    hog_function.hog = new_hog
                    hog_function.bytecode = new_bytecode
                    hog_function.save(update_fields=["hog", "bytecode"])

        # Output summary
        duration = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"Update completed in {duration:.2f}s. Found: {total_found}, Updated: {updated_count}, Failed: {len(failed)}"
            )
        )

        if failed:
            self.stdout.write(self.style.WARNING(f"{len(failed)} hog function(s) failed to compile and were skipped:"))
            for fn_id, team_id, enabled, error in failed:
                self.stdout.write(f"  id={fn_id} team={team_id} enabled={enabled} error={error}")
