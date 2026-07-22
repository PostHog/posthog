from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.models.integration import CONFIG_LEGACY_OAUTH_CLIENT, Integration, issuing_oauth_client_ids

logger = structlog.get_logger(__name__)

# Kinds whose current client id we can name, so `aud` can be compared against it.
CURRENT_CLIENT_ID_SETTING = {"bing-ads": "BING_ADS_CLIENT_ID"}


class Command(BaseCommand):
    """Classify OAuth connections by the app they were established with.

    Safe to re-run, and worth re-running: this rewrites `config` the same way the refresh sweep
    does, so a refresh landing mid-pass can overwrite the flag on that row with its own
    (equally valid) verdict. Both paths converge on the same answer, and a second pass settles
    any row that lost the race.
    """

    help = "Flag OAuth integrations still connected through a superseded client id, so the product can ask those teams to reconnect before the old app is retired."

    def add_arguments(self, parser):
        parser.add_argument("--kind", default="bing-ads", choices=sorted(CURRENT_CLIENT_ID_SETTING))
        parser.add_argument("--dry-run", action="store_true", help="Report the counts without writing")

    def handle(self, *args, **options):
        kind = options["kind"]
        dry_run = options["dry_run"]

        current_client_id = getattr(settings, CURRENT_CLIENT_ID_SETTING[kind], "")
        if not current_client_id:
            raise CommandError(f"{CURRENT_CLIENT_ID_SETTING[kind]} is not set, so nothing can be compared against it")

        counts = {"legacy": 0, "current": 0, "unknown": 0}
        for integration in Integration.objects.filter(kind=kind).iterator():
            client_ids = issuing_oauth_client_ids(integration)
            if not client_ids:
                # No id_token to read, so the refresh path stays the only signal for this row.
                counts["unknown"] += 1
                continue

            is_legacy = current_client_id not in client_ids
            counts["legacy" if is_legacy else "current"] += 1

            already_flagged = bool(integration.config.get(CONFIG_LEGACY_OAUTH_CLIENT))
            if already_flagged == is_legacy or dry_run:
                continue

            if is_legacy:
                integration.config[CONFIG_LEGACY_OAUTH_CLIENT] = True
            else:
                integration.config.pop(CONFIG_LEGACY_OAUTH_CLIENT, None)
            integration.save(update_fields=["config"])

        self.stdout.write(
            f"{kind}: {counts['legacy']} on a superseded client, {counts['current']} current, "
            f"{counts['unknown']} without an id_token to read" + (" (dry run, nothing written)" if dry_run else "")
        )
