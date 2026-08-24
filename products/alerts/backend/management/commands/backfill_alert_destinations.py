"""Backfill AlertIdentity and AlertDestination rows from legacy filter-based ownership.

Classifies every alert-owned HogFunction by its alert_id property filter, groups
executors into one logical AlertDestination per (alert, destination type,
canonical destination inputs), and sets alert_destination_id and alert_event_kind.

Conservative by design: ambiguous groups are reported and skipped — they keep
working through the legacy filter path until a human resolves them.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Collection
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from products.alerts.backend.destination_configs import DESTINATION_TEMPLATE_IDS
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.models.alert_identity import AlertDestination, AlertIdentity, AlertProduct
from products.billing_alerts.backend.models import BillingAlertConfiguration
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.logs.backend.models import LogsAlertConfiguration

# Maps internal event name → (product, alert_event_kind). Covers every alert-
# managed internal event currently emitted.
_EVENT_TO_KIND: dict[str, tuple[AlertProduct, str]] = {
    "$insight_alert_firing": (AlertProduct.INSIGHT, "firing"),
    "$logs_alert_firing": (AlertProduct.LOGS, "firing"),
    "$logs_alert_resolved": (AlertProduct.LOGS, "resolved"),
    "$logs_alert_errored": (AlertProduct.LOGS, "errored"),
    "$logs_alert_auto_disabled": (AlertProduct.LOGS, "broken"),
    "$billing_alert_firing": (AlertProduct.BILLING, "firing"),
    "$billing_alert_resolved": (AlertProduct.BILLING, "resolved"),
    "$billing_alert_errored": (AlertProduct.BILLING, "errored"),
    "$billing_alert_auto_disabled": (AlertProduct.BILLING, "broken"),
}

# Where to look up identity metadata (organization, execution team) per product.
_PRODUCT_CONFIG_MODELS = {
    AlertProduct.INSIGHT: AlertConfiguration,
    AlertProduct.LOGS: LogsAlertConfiguration,
    AlertProduct.BILLING: BillingAlertConfiguration,
}

# Inputs that identify the destination target (vs. per-event payload). Used to
# decide which HogFunctions belong to the same logical destination group.
_DESTINATION_IDENTITY_INPUT_KEYS = ("slack_workspace", "channel", "url", "webhookUrl")


def _classify_owned_hog_functions() -> dict[str, list[HogFunction]]:
    """Return alert_id (as str) → HogFunctions owned by that alert via filters.

    Only HogFunctions that carry both (a) a known alert internal event id in
    filters.events and (b) an exact alert_id property filter are classified.
    Anything else is returned in an "unclassified" list under the empty key.
    """
    owned: dict[str, list[HogFunction]] = defaultdict(list)
    for event_id in _EVENT_TO_KIND:
        for hf in HogFunction.objects.filter(
            deleted=False,
            type="internal_destination",
            template_id__in=DESTINATION_TEMPLATE_IDS.values(),
            filters__events__contains=[{"id": event_id, "type": "events"}],
        ):
            alert_id = _extract_alert_id_filter(hf)
            if alert_id:
                owned[alert_id].append(hf)

    return owned


def _extract_alert_id_filter(hf: HogFunction) -> str | None:
    filters = hf.filters or {}
    properties = filters.get("properties") or []
    if not isinstance(properties, list):
        return None
    for prop in properties:
        if (
            isinstance(prop, dict)
            and prop.get("key") == "alert_id"
            and prop.get("operator") == "exact"
            and prop.get("type") == "event"
            and prop.get("value")
        ):
            return str(prop["value"])
    return None


def _event_kind_for(hf: HogFunction) -> tuple[AlertProduct, str] | None:
    filters = hf.filters or {}
    events = filters.get("events") or []
    if not isinstance(events, list):
        return None
    for event in events:
        if isinstance(event, dict) and event.get("type") == "events":
            result = _EVENT_TO_KIND.get(str(event.get("id")))
            if result is not None:
                return result
    return None


def _destination_group_key(hf: HogFunction) -> tuple[str, str]:
    """Group key identifying one logical destination: (template_id, canonical target inputs)."""
    canonical: dict[str, Any] = {}
    inputs = hf.inputs or {}
    for key in _DESTINATION_IDENTITY_INPUT_KEYS:
        value = inputs.get(key, {}).get("value") if isinstance(inputs.get(key), dict) else None
        if value is not None:
            canonical[key] = value
    return (hf.template_id or "", json.dumps(canonical, sort_keys=True))


class Command(BaseCommand):
    help = __doc__ or "Backfill AlertIdentity/AlertDestination plus HogFunction ownership columns."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Classify and report without writing any rows.",
        )
        parser.add_argument(
            "--alert-ids",
            nargs="*",
            default=None,
            help="Only backfill these alert UUIDs (defaults to all classified alerts).",
        )

    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]
        restrict: Collection[str] | None = options["alert_ids"]

        self.stdout.write("Classifying alert-owned HogFunctions...")
        owned = _classify_owned_hog_functions()
        self.stdout.write(f"  {sum(len(v) for v in owned.values())} HogFunctions across {len(owned)} alerts.")

        alerts_processed = 0
        identities_created = 0
        destinations_created = 0
        ambiguous = 0
        executions_stamped = 0

        for alert_id_str, hog_functions in sorted(owned.items()):
            if restrict and alert_id_str not in restrict:
                continue
            try:
                alert_uuid = UUID(alert_id_str)
            except ValueError:
                self.stdout.write(self.style.WARNING(f"  alert_id={alert_id_str!r} is not a UUID; skipping."))
                ambiguous += len(hog_functions)
                continue

            sample = hog_functions[0]
            classification = _event_kind_for(sample)
            if classification is None:
                self.stdout.write(
                    self.style.WARNING(f"  alert_id={alert_id_str} has no recognisable event kind; skipping.")
                )
                ambiguous += len(hog_functions)
                continue
            product, _ = classification

            # Every function for the alert must be the same product.
            products = {_event_kind_for(hf)[0] for hf in hog_functions if _event_kind_for(hf)}
            if len(products) != 1:
                self.stdout.write(
                    self.style.WARNING(
                        f"  alert_id={alert_id_str} mixes products {sorted(p.value for p in products)}; skipping."
                    )
                )
                ambiguous += len(hog_functions)
                continue

            try:
                identity, identity_created = self._ensure_identity(
                    dry_run=dry_run, product=product, alert_uuid=alert_uuid
                )
            except CommandError as e:
                self.stdout.write(self.style.WARNING(f"  alert_id={alert_id_str}: {e}"))
                ambiguous += len(hog_functions)
                continue
            identities_created += int(identity_created)

            # Skip HogFunctions already stamped to a destination (idempotent re-runs).
            unstamped_functions = [hf for hf in hog_functions if hf.alert_destination_id is None]

            groups: dict[tuple[str, str], list[HogFunction]] = defaultdict(list)
            for hf in unstamped_functions:
                groups[_destination_group_key(hf)].append(hf)

            if dry_run:
                destinations_created += len(groups)
                executions_stamped += len(hog_functions)
            else:
                with transaction.atomic():
                    for (template_id, _canonical), members in groups.items():
                        kinds = {(_event_kind_for(hf) or (product, ""))[1] for hf in members}
                        if len(kinds) != len(members):
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  alert_id={alert_id_str} group {template_id!r} has duplicate event kinds {sorted(kinds)}; skipping group."
                                )
                            )
                            ambiguous += len(members)
                            continue
                        destination_type = _destination_type_value(template_id)
                        destination = AlertDestination.objects.create(
                            alert=identity,
                            type=destination_type,
                            name=members[0].name or "Destination",
                        )
                        destinations_created += 1
                        for hf in members:
                            classification = _event_kind_for(hf)
                            if classification is None:
                                ambiguous += 1
                                continue
                            _, event_kind = classification
                            hf.alert_destination = destination
                            hf.alert_event_kind = event_kind
                            hf.save(update_fields=["alert_destination", "alert_event_kind"])
                            executions_stamped += 1

            alerts_processed += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Backfill summary"))
        self.stdout.write(f"  dry_run:             {dry_run}")
        self.stdout.write(f"  alerts_processed:    {alerts_processed}")
        self.stdout.write(f"  identities_created:  {identities_created}")
        self.stdout.write(f"  destinations_created:{destinations_created}")
        self.stdout.write(f"  executors_stamped:   {executions_stamped}")
        self.stdout.write(f"  ambiguous:           {ambiguous}")

    def _ensure_identity(
        self, *, dry_run: bool, product: AlertProduct, alert_uuid: UUID
    ) -> tuple[AlertIdentity, bool]:
        config_model = _PRODUCT_CONFIG_MODELS[product]
        config = config_model.objects.filter(id=alert_uuid).select_related("team").first()
        if config is None:
            raise CommandError(f"no {config_model.__name__} row for alert {alert_uuid}; skipping.")

        if product is AlertProduct.BILLING:
            assert isinstance(config, BillingAlertConfiguration)
            organization_id = config.organization_id
            execution_team_id = config.team_id
        else:
            assert isinstance(config, (AlertConfiguration, LogsAlertConfiguration))
            organization_id = config.team.organization_id
            execution_team_id = config.team_id

        if dry_run:
            identity = AlertIdentity(
                id=alert_uuid,
                product=product,
                organization_id=organization_id,
                execution_team_id=execution_team_id,
            )
            return identity, True

        identity, created = AlertIdentity.objects.get_or_create(
            id=alert_uuid,
            defaults={
                "product": product,
                "organization_id": organization_id,
                "execution_team_id": execution_team_id,
            },
        )
        # Link the product configuration back to the shared identity.
        if config.alert_id is None:
            config.alert_id = identity.id
            config.save(update_fields=["alert"])
        return identity, created


def _destination_type_value(template_id: str) -> str:
    for destination_type, tid in DESTINATION_TEMPLATE_IDS.items():
        if tid == template_id:
            return destination_type.value
    return template_id
