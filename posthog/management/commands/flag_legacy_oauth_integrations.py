from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Func, JSONField, Value

import structlog

from posthog.models.integration import CONFIG_LEGACY_OAUTH_CLIENT, Integration, issuing_oauth_client_ids

logger = structlog.get_logger(__name__)

# Kinds whose current client id we can name, so `aud` can be compared against it.
CURRENT_CLIENT_ID_SETTING = {"bing-ads": "BING_ADS_CLIENT_ID"}

# JSON-level merges so a concurrent refresh's read-modify-write of `config` (backoff counters,
# refreshed_at) can't be clobbered by this pass, nor vice versa.
_FLAG_SET = Func(
    F("config"),
    Value(f"{{{CONFIG_LEGACY_OAUTH_CLIENT}}}"),
    function="jsonb_set",
    template="%(function)s(%(expressions)s::text[], 'true'::jsonb)",
    output_field=JSONField(),
)
_FLAG_CLEARED = Func(
    F("config"),
    Value(CONFIG_LEGACY_OAUTH_CLIENT),
    template="%(expressions)s",
    arg_joiner=" - ",
    output_field=JSONField(),
)


class Command(BaseCommand):
    """Classify OAuth connections by the app they were established with.

    Safe to re-run, and worth re-running: the refresh sweep rewrites `config` wholesale, so a
    refresh whose in-memory snapshot predates this pass can overwrite the flag on that row with
    its own (equally valid) verdict. Both paths converge on the same answer, and a second pass
    settles any row that lost the race.
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

            Integration.objects.filter(pk=integration.pk).update(config=_FLAG_SET if is_legacy else _FLAG_CLEARED)

        self.stdout.write(
            f"{kind}: {counts['legacy']} on a superseded client, {counts['current']} current, "
            f"{counts['unknown']} without an id_token to read" + (" (dry run, nothing written)" if dry_run else "")
        )
