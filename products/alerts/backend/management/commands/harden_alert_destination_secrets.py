"""Move alert-owned webhook URLs out of readable hog function fields.

Alert-owned destination rows created before webhook inputs were stored secret carry the
full webhook URL (a channel credential) in the function name and in the readable inputs
field. This command renames those rows to keep only the URL host and flips the
credential-bearing schema entries to secret, so saving relocates the value into
encrypted inputs. User-created destinations, including legacy insight-alert ones, are
not touched.

Dry run by default; pass --live to apply.
"""

from typing import Any

from django.core.management.base import BaseCommand

import structlog

from posthog.cdp.internal_events import is_managed_alert_internal_event

from products.alerts.backend.destination_configs import DESTINATION_SECRET_INPUT_KEYS, DESTINATION_TEMPLATE_IDS
from products.alerts.backend.destinations import _DESTINATION_NAME_SEPARATOR, _receipt_safe_name
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)

_TEMPLATE_ID_TO_SECRET_KEYS: dict[str, tuple[str, ...]] = {
    template_id: DESTINATION_SECRET_INPUT_KEYS[destination_type]
    for destination_type, template_id in DESTINATION_TEMPLATE_IDS.items()
    if DESTINATION_SECRET_INPUT_KEYS[destination_type]
}


def _host_only_destination_segment(name: str) -> str:
    """Names read "<product> — <alert> (<kind>) → <destination>". Only the destination segment
    carries the webhook URL, and an alert name may legitimately contain a URL of its own, so
    rewrite the trailing segment and leave the prefix as the user wrote it."""
    prefix, separator, destination = name.rpartition(_DESTINATION_NAME_SEPARATOR)
    if not separator:
        return _receipt_safe_name(name)
    return f"{prefix}{separator}{_receipt_safe_name(destination)}"


def _is_alert_owned(hog_function: HogFunction) -> bool:
    events = (hog_function.filters or {}).get("events") or []
    return any(is_managed_alert_internal_event(event.get("id")) for event in events if isinstance(event, dict))


class Command(BaseCommand):
    help = "Move alert-owned webhook URLs into encrypted inputs and strip them from function names"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--live", action="store_true", help="Apply changes; without it the command only reports")

    def handle(self, *args: Any, **options: Any) -> None:
        live: bool = options["live"]
        scanned = 0
        changed = 0

        # Cross-team by design: a one-off backfill over every alert-owned destination row.
        candidates = HogFunction.objects.filter(
            type="internal_destination",
            deleted=False,
            template_id__in=_TEMPLATE_ID_TO_SECRET_KEYS.keys(),
        ).iterator()

        for hog_function in candidates:
            if not _is_alert_owned(hog_function):
                continue
            scanned += 1

            secret_keys = _TEMPLATE_ID_TO_SECRET_KEYS.get(hog_function.template_id or "", ())
            new_schema = []
            schema_changed = False
            for schema in hog_function.inputs_schema or []:
                if schema.get("key") in secret_keys and not schema.get("secret"):
                    schema = {**schema, "secret": True}
                    schema_changed = True
                new_schema.append(schema)

            new_name = _host_only_destination_segment(hog_function.name or "")
            name_changed = new_name != (hog_function.name or "")

            if not schema_changed and not name_changed:
                continue
            changed += 1

            if not live:
                logger.info(
                    "would harden alert destination",
                    hog_function_id=str(hog_function.id),
                    team_id=hog_function.team_id,
                    rename=name_changed,
                    secret_inputs=schema_changed,
                )
                continue

            hog_function.inputs_schema = new_schema
            hog_function.name = new_name
            # A full save so move_secret_inputs relocates the credential and the post_save
            # signal reloads the function on workers.
            hog_function.save()
            logger.info(
                "hardened alert destination",
                hog_function_id=str(hog_function.id),
                team_id=hog_function.team_id,
            )

        mode = "applied" if live else "dry run - re-run with --live to apply"
        self.stdout.write(f"Scanned {scanned} alert-owned destinations, {changed} needed hardening ({mode})")
