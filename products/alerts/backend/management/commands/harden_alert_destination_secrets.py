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
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db import transaction

import structlog

from posthog.cdp.internal_events import is_managed_alert_internal_event
from posthog.dataclasses import frozen

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


@frozen
class _HardeningPlan:
    inputs_schema: list[dict]
    name: str
    schema_changed: bool
    name_changed: bool

    @property
    def has_changes(self) -> bool:
        return self.schema_changed or self.name_changed


def _plan_hardening(hog_function: HogFunction) -> _HardeningPlan:
    secret_keys = _TEMPLATE_ID_TO_SECRET_KEYS.get(hog_function.template_id or "", ())
    new_schema = []
    schema_changed = False
    for schema in hog_function.inputs_schema or []:
        if schema.get("key") in secret_keys and not schema.get("secret"):
            schema = {**schema, "secret": True}
            schema_changed = True
        new_schema.append(schema)

    new_name = _host_only_destination_segment(hog_function.name or "")
    return _HardeningPlan(
        inputs_schema=new_schema,
        name=new_name,
        schema_changed=schema_changed,
        name_changed=new_name != (hog_function.name or ""),
    )


class Command(BaseCommand):
    help = "Move alert-owned webhook URLs into encrypted inputs and strip them from function names"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--live", action="store_true", help="Apply changes; without it the command only reports")

    def handle(self, *args: Any, **options: Any) -> None:
        live: bool = options["live"]
        scanned = 0
        to_harden: list[UUID] = []

        # Cross-team by design: a one-off backfill over every alert-owned destination row.
        # Scan without a lock first so the read cursor never spans a write transaction, then
        # apply each change under its own row lock below.
        candidates = HogFunction.objects.filter(
            type="internal_destination",
            deleted=False,
            template_id__in=_TEMPLATE_ID_TO_SECRET_KEYS.keys(),
        ).iterator()

        for hog_function in candidates:
            if not _is_alert_owned(hog_function):
                continue
            scanned += 1

            plan = _plan_hardening(hog_function)
            if not plan.has_changes:
                continue
            to_harden.append(hog_function.id)

            if not live:
                logger.info(
                    "would harden alert destination",
                    hog_function_id=str(hog_function.id),
                    team_id=hog_function.team_id,
                    rename=plan.name_changed,
                    secret_inputs=plan.schema_changed,
                )

        hardened = 0
        if live:
            for hog_function_id in to_harden:
                if self._harden_locked(hog_function_id):
                    hardened += 1

        if live:
            self.stdout.write(
                f"Scanned {scanned} alert-owned destinations, hardened {hardened} of {len(to_harden)} candidates (applied)"
            )
        else:
            self.stdout.write(
                f"Scanned {scanned} alert-owned destinations, {len(to_harden)} need hardening "
                "(dry run - re-run with --live to apply)"
            )

    def _harden_locked(self, hog_function_id: UUID) -> bool:
        """Lock the row, re-check it after the lock, and save the hardened fields from the
        locked copy. Locking closes the window in which a concurrent soft-delete could be
        reverted by a stale full-row save, and recomputing from the locked row preserves any
        edit that landed between the scan and now."""
        with transaction.atomic():
            hog_function = HogFunction.objects.select_for_update().filter(id=hog_function_id, deleted=False).first()
            if hog_function is None:
                # Deleted (or already hardened away) since the scan; do not resurrect it.
                logger.info("skipped alert destination gone since scan", hog_function_id=str(hog_function_id))
                return False

            plan = _plan_hardening(hog_function)
            if not plan.has_changes:
                return False

            hog_function.inputs_schema = plan.inputs_schema
            hog_function.name = plan.name
            # A full save so move_secret_inputs relocates the credential and the post_save
            # signal reloads the function on workers.
            hog_function.save()
            logger.info(
                "hardened alert destination",
                hog_function_id=str(hog_function.id),
                team_id=hog_function.team_id,
            )
            return True
