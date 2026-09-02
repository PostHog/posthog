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
    # Skip a destination entirely unless its hog contains this string. For options whose replacements
    # would otherwise also match code deliberately left behind (e.g. a sunset version kept dead on
    # purpose), this pins the run to the intended cohort.
    only_if_contains: NotRequired[str]


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
            # LinkedIn supports each dated version for a minimum of one year, then rejects it with a
            # 426 NONEXISTENT_VERSION on every call. 202508 passed that mark on 2026-08-01. 202409 is
            # deliberately excluded: those destinations have been failing for a year already, so
            # bumping them would abruptly revive dormant-but-enabled destinations and resume
            # conversions into customers' LinkedIn Ads accounts without warning. Reviving those is
            # handled separately with customer awareness.
            #
            # 202607 also enforces firstName and lastName within userInfo, so the version bump alone
            # would turn the 426 into a 422 for any event lacking a name. The header bump and a
            # userInfo guard have to land together for a destination to send successfully.
            #
            # Two hog shapes carry the 202508 header. Destinations created since Oct 2025 collect
            # userInfo into a local and guard on its length; the guard just needs tightening to
            # require both names. Older destinations (including those bumped from 202409 by
            # linked-api-version-update) instead build body.user.userInfo in place with no guard and
            # always send userInfo, even empty, so their whole userInfo section is replaced with the
            # collect-and-guard form. only_if_contains keeps the userInfo replacements, which match
            # both eras' code, from touching the excluded 202409 destinations.
            "linkedin-api-version-update-202607": {
                "template_id": "template-linkedin-ads",
                "only_if_contains": "'LinkedIn-Version': '202508'",
                "replacements": [
                    {
                        "from_string": "'LinkedIn-Version': '202508'",
                        "to_string": "'LinkedIn-Version': '202607'",
                    },
                    {
                        "from_string": "if (length(keys(userInfo)) >= 1) {",
                        "to_string": "if (not empty(userInfo['firstName']) and not empty(userInfo['lastName'])) {",
                    },
                    {
                        "from_string": "'userIds': [],\n        'userInfo': {}\n     },",
                        "to_string": "'userIds': []\n     },",
                    },
                    {
                        "from_string": "for (let key, value in inputs.userInfo) {\n    if (not empty(value)) {\n        body.user.userInfo[key] := value\n    }\n}",
                        "to_string": "let userInfo := {}\nfor (let key, value in inputs.userInfo) {\n    if (not empty(value)) {\n        userInfo[key] := value\n    }\n}\nif (not empty(userInfo['firstName']) and not empty(userInfo['lastName'])) {\n    body.user['userInfo'] := userInfo\n}",
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
            # Google Ads API v21 sunsets 2026-08-05 (VERSION_SUNSET). Bump v19-v23 destinations to v24
            # so the v21 majority keeps working past the sunset. v18 is deliberately excluded: Google
            # has already removed it, so those destinations 404 today; bumping them would abruptly
            # revive dormant-but-enabled dead destinations and resume conversions into customers'
            # Google Ads accounts without warning. Reviving v18 (and older v17) destinations is handled
            # separately with customer awareness. Destinations carry whatever version the template
            # pinned at creation; only one matches per destination, and a v24 no-op is skipped.
            "google-ads-api-version-update": {
                "template_id": "template-google-ads",
                "replacements": [
                    {"from_string": f"googleads.googleapis.com/v{v}/", "to_string": "googleads.googleapis.com/v24/"}
                    for v in range(19, 24)
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

                required_marker = replaceOption.get("only_if_contains")
                if required_marker and required_marker not in destination.hog:
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
