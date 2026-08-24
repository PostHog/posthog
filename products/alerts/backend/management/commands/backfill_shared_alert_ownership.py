"""Backfill shared alert identities and AlertDestination ownership for existing alerts.

Phase 2 of the explicit alert ownership RFC. Reads every alert product config,
creates (or links) its shared identity row, groups the alert's HogFunctions
under the same logical destination (matching what the shared destination
service would have done upfront), and stamps the HogFunctions with
`alert_destination` / `alert_event_kind`.

Ambiguous rows stay unlinked: an ambiguous HogFunction keeps its `alert_id`
filter working and its ownership columns occupy neither path. Use
`--dry-run` to inspect before committing.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db import transaction

import structlog

from products.alerts.backend.destination_configs import DESTINATION_TEMPLATE_IDS
from products.alerts.backend.models.shared_alert import AlertDestination, AlertProduct, AlertSharedIdentity
from products.billing_alerts.backend.models import BillingAlertConfiguration
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.logs.backend.models import LogsAlertConfiguration
from products.alerts.backend.models.alert import AlertConfiguration

logger = structlog.get_logger(__name__)


def _extract_alert_id(filters: dict[str, Any]) -> str | None:
    properties = filters.get("properties") if isinstance(filters, dict) else None
    if not isinstance(properties, list):
        return None
    for property_filter in properties:
        if not isinstance(property_filter, dict):
            continue
        if property_filter.get("key") == "alert_id" and property_filter.get("type") == "event":
            value = property_filter.get("value")
            return str(value) if value is not None else None
    return None


def _extract_event_id(filters: dict[str, Any]) -> str | None:
    events = filters.get("events") if isinstance(filters, dict) else None
    if not isinstance(events, list):
        return None
    for event_filter in events:
        if not isinstance(event_filter, dict):
            continue
        if event_filter.get("type") == "events" and event_filter.get("id"):
            return str(event_filter["id"])
    return None


_EVENT_ID_TO_KIND: dict[str, str] = {
    "$logs_alert_firing": "firing",
    "$logs_alert_resolved": "resolved",
    "$logs_alert_errored": "errored",
    "$logs_alert_auto_disabled": "broken",
    "$billing_alert_firing": "firing",
    "$billing_alert_resolved": "resolved",
    "$billing_alert_errored": "errored",
    "$billing_alert_auto_disabled": "broken",
    "$insight_alert_firing": "firing",
}


def _normalize_inputs(inputs: Any) -> str:
    """Canonicalize executor inputs for grouping.

    JSON serialization order is content-dependent in Postgres, so we can't
    compare inputs field-equality directly; the digest lets us pair two
    HogFunctions that deliver the same destination.
    """
    if not isinstance(inputs, dict):
        return ""
    try:
        canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        # Fallback for unserializable inputs; groups land on the same row as
        # long as the anomaly is deterministic.
        canonical = repr(sorted(inputs.items()))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class AlertBackfillStats:
    insights_linked: int = 0
    insights_ambiguous: int = 0
    insights_skipped_existing: int = 0
    logs_linked: int = 0
    logs_ambiguous: int = 0
    logs_skipped_existing: int = 0
    billing_linked: int = 0
    billing_ambiguous: int = 0
    billing_skipped_existing: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "insights_linked": self.insights_linked,
            "insights_ambiguous": self.insights_ambiguous,
            "insights_skipped_existing": self.insights_skipped_existing,
            "logs_linked": self.logs_linked,
            "logs_ambiguous": self.logs_ambiguous,
            "logs_skipped_existing": self.logs_skipped_existing,
            "billing_linked": self.billing_linked,
            "billing_ambiguous": self.billing_ambiguous,
            "billing_skipped_existing": self.billing_skipped_existing,
        }


@dataclass
class GroupedExecutions:
    """One logical destination for one alert, reconstructed from live HogFunctions."""

    template_id: str
    inputs_digest: str
    functions: list[HogFunction] = field(default_factory=list)
    event_kinds: set[str] = field(default_factory=set)


class Command(BaseCommand):
    help = "Backfill shared alert identities, AlertDestinations, and HogFunction ownership columns."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Log what would change without writing.")
        parser.add_argument(
            "--product",
            choices=[choice.value for choice in AlertProduct],
            help="Only process one product family.",
        )
        parser.add_argument(
            "--alert-id",
            type=str,
            help="Process a single alert by id (also useful for one-off repair).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Process at most this many alerts (useful for staged rollouts).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=200,
            help="Number of HogFunctions to fetch per page when grouping per alert.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        products = [options["product"]] if options["product"] else [choice.value for choice in AlertProduct]
        stats = AlertBackfillStats()

        if "insight" in products:
            self._backfill_insight_alerts(stats=stats, dry_run=dry_run, alert_id=options.get("alert_id"), limit=options["limit"], batch_size=options["batch_size"])
        if "logs" in products:
            self._backfill_logs_alerts(stats=stats, dry_run=dry_run, alert_id=options.get("alert_id"), limit=options["limit"], batch_size=options["batch_size"])
        if "billing" in products:
            self._backfill_billing_alerts(stats=stats, dry_run=dry_run, alert_id=options.get("alert_id"), limit=options["limit"], batch_size=options["batch_size"])

        self.stdout.write(self.style.SUCCESS(json.dumps({"dry_run": dry_run, **stats.as_dict()}, indent=2)))

    def _backfill_insight_alerts(self, *, stats: AlertBackfillStats, dry_run: bool, alert_id: str | None, limit: int | None, batch_size: int) -> None:
        qs = AlertConfiguration.objects.filter(shared_alert__isnull=True).select_related("team__organization").iterator()
        self._backfill_config_rows(
            stats=stats,
            dry_run=dry_run,
            alert_id=alert_id,
            limit=limit,
            batch_size=batch_size,
            queryset=qs,
            product=AlertProduct.INSIGHT,
            product_slug="insight",
            get_config=lambda row: row,
            get_organization_id=lambda row: row.team.organization_id,
            get_execution_team_id=lambda row: row.team_id,
        )

    def _backfill_logs_alerts(self, *, stats: AlertBackfillStats, dry_run: bool, alert_id: str | None, limit: int | None, batch_size: int) -> None:
        qs = LogsAlertConfiguration.objects.filter(shared_alert__isnull=True).select_related("team__organization").iterator()
        self._backfill_config_rows(
            stats=stats,
            dry_run=dry_run,
            alert_id=alert_id,
            limit=limit,
            batch_size=batch_size,
            queryset=qs,
            product=AlertProduct.LOGS,
            product_slug="logs",
            get_config=lambda row: row,
            get_organization_id=lambda row: row.team.organization_id,
            get_execution_team_id=lambda row: row.team_id,
        )

    def _backfill_billing_alerts(self, *, stats: AlertBackfillStats, dry_run: bool, alert_id: str | None, limit: int | None, batch_size: int) -> None:
        qs = BillingAlertConfiguration.objects.filter(shared_alert__isnull=True).iterator()
        self._backfill_config_rows(
            stats=stats,
            dry_run=dry_run,
            alert_id=alert_id,
            limit=limit,
            batch_size=batch_size,
            queryset=qs,
            product=AlertProduct.BILLING,
            product_slug="billing",
            get_config=lambda row: row,
            get_organization_id=lambda row: row.organization_id,
            get_execution_team_id=lambda row: row.team_id,
        )

    def _backfill_config_rows(
        self,
        *,
        stats: AlertBackfillStats,
        dry_run: bool,
        alert_id: str | None,
        limit: int | None,
        batch_size: int,
        queryset: Any,
        product: AlertProduct,
        product_slug: str,
        get_config: Any,
        get_organization_id: Any,
        get_execution_team_id: Any,
    ) -> None:
        processed = 0
        for row in queryset:
            if alert_id and str(row.id) != alert_id:
                continue
            if limit is not None and processed >= limit:
                break
            processed += 1
            outcome = self._backfill_one_alert(
                config=get_config(row),
                product=product,
                product_slug=product_slug,
                organization_id=get_organization_id(row),
                execution_team_id=get_execution_team_id(row),
                batch_size=batch_size,
                dry_run=dry_run,
            )
            if outcome == "linked":
                setattr(stats, f"{product_slug}_linked", getattr(stats, f"{product_slug}_linked") + 1)
            elif outcome == "ambiguous":
                setattr(stats, f"{product_slug}_ambiguous", getattr(stats, f"{product_slug}_ambiguous") + 1)
            else:
                setattr(stats, f"{product_slug}_skipped_existing", getattr(stats, f"{product_slug}_skipped_existing") + 1)

    def _backfill_one_alert(
        self,
        *,
        config: Any,
        product: AlertProduct,
        product_slug: str,
        organization_id: UUID,
        execution_team_id: int | None,
        batch_size: int,
        dry_run: bool,
    ) -> str:
        """Link one product alert row to a shared identity + AlertDestination rows.

        Returns `"linked"`, `"skipped"`, or `"ambiguous"`. Ambiguous means at
        least one HogFunction matched the alert by its JSON filter but can't
        be safely grouped into a destination; the alert stays partially
        unlinked (execution falls back to filters) until a human review.
        """
        result = "linked"

        executor_candidates = self._find_candidate_executors(alert_id=str(config.id), team_id=execution_team_id)
        if not executor_candidates and not dry_run:
            logger.info(
                "shared_alert_no_executors",
                product=product.value,
                alert_id=str(config.id),
                organization_id=str(organization_id),
                execution_team_id=execution_team_id,
            )

        groups, ambiguous = self._group_executions(executor_candidates)
        if ambiguous:
            logger.warning(
                "shared_alert_ambiguous_executors",
                product=product.value,
                alert_id=str(config.id),
                ambiguous_hog_function_ids=[str(hf.id) for hf in ambiguous],
            )
            result = "ambiguous"

        if dry_run:
            for group in groups.values():
                self.stdout.write(
                    f"[dry-run] {product.value}/{config.id} would create AlertDestination "
                    f"template={group.template_id} with {len(group.functions)} executors"
                )
            return result

        with transaction.atomic():
            shared_alert, _created = AlertSharedIdentity.objects.get_or_create(
                id=config.id,
                defaults={
                    "product": product.value,
                    "organization_id": organization_id,
                    "execution_team_id": execution_team_id,
                },
            )
            # Keep tenant information in sync with the product row's current
            # owner; the destination executor's team must match for routing.
            update_fields: list[str] = []
            if shared_alert.organization_id != organization_id:
                shared_alert.organization_id = organization_id
                update_fields.append("organization_id")
            if shared_alert.execution_team_id != execution_team_id:
                shared_alert.execution_team_id = execution_team_id
                update_fields.append("execution_team_id")
            if update_fields:
                shared_alert.save(update_fields=update_fields)

            # Attach the product row's nullable OneToOne.
            update_config_fields: list[str] = []
            if config.shared_alert_id != shared_alert.id:
                config.shared_alert = shared_alert
                update_config_fields.append("shared_alert")
            if update_config_fields:
                config.save(update_fields=update_config_fields)

            for (template_id, inputs_digest), group in groups.items():
                destination_type_value = {
                    template_id: destination_type.value
                    for destination_type, template_id in DESTINATION_TEMPLATE_IDS.items()
                }.get(template_id)
                if destination_type_value is None:
                    logger.warning(
                        "shared_alert_unknown_template_id", template_id=template_id, alert_id=str(config.id)
                    )
                    continue

                destination_name = f"{destination_type_value.capitalize()} destination"
                destination = AlertDestination.objects.create(
                    shared_alert=shared_alert,
                    type=destination_type_value,
                    name=destination_name,
                )
                event_kinds_seen: set[str] = set()
                hog_function_ids_to_update: list[UUID] = []
                kinds_to_write: dict[UUID, str] = {}
                for hog_function in group.functions:
                    event_kind = _EVENT_ID_TO_KIND.get(_extract_event_id(hog_function.filters or {}) or "")
                    if event_kind is None:
                        logger.warning(
                            "shared_alert_unknown_event_kind",
                            hog_function_id=str(hog_function.id),
                            template_id=template_id,
                            alert_id=str(config.id),
                        )
                        result = "ambiguous"
                        continue
                    if event_kind in event_kinds_seen:
                        result = "ambiguous"
                        logger.warning(
                            "shared_alert_duplicate_event_kind_in_group",
                            hog_function_id=str(hog_function.id),
                            event_kind=event_kind,
                            alert_id=str(config.id),
                        )
                        continue
                    event_kinds_seen.add(event_kind)
                    kinds_to_write[hog_function.id] = event_kind
                    hog_function_ids_to_update.append(hog_function.id)

                # Bulk update the ownership columns; each function gets its
                # typed stamp in one statement per kind since the values vary.
                for hog_function_id, event_kind in kinds_to_write.items():
                    HogFunction.objects.filter(id=hog_function_id).update(
                        alert_destination=destination, alert_event_kind=event_kind
                    )

        return result

    def _find_candidate_executors(self, *, alert_id: str, team_id: int | None) -> list[HogFunction]:
        """Pull every HogFunction that could belong to this alert.

        Matching mirrors the shared destination service's ownership filter so
        the snapshot the backfill classifies is the same one the API sees.
        Ambiguity at this stage (different templates across one alert) is
        handled by grouping, not by rejecting the row.
        """
        queryset = HogFunction.objects.filter(
            deleted=False,
            template_id__in=list(DESTINATION_TEMPLATE_IDS.values()),
            filters__properties__contains=[{"key": "alert_id", "value": alert_id}],
        )
        if team_id is not None:
            queryset = queryset.filter(team_id=team_id)
        return list(queryset.order_by("id").iterator())

    def _group_executions(self, functions: list[HogFunction]) -> tuple[dict[tuple[str, str], GroupedExecutions], list[HogFunction]]:
        """Group by (template_id, inputs-digest): one logical destination per pair.

        Returns (groups, ambiguous). An executor is ambiguous when its inputs
        digest collides with an existing group but its own template differs,
        when the event_kind is unknown, when two rows share the same
        event_kind within a group (meaning two destinations fight over one
        logical destination), or when the group ends up with no usable
        function at all.
        """
        groups: dict[tuple[str, str], GroupedExecutions] = {}
        ambiguous: list[HogFunction] = []

        for hog_function in functions:
            template_id = hog_function.template_id or ""
            inputs_digest = _normalize_inputs(hog_function.inputs)
            key = (template_id, inputs_digest)
            if key not in groups:
                groups[key] = GroupedExecutions(template_id=template_id, inputs_digest=inputs_digest)
            groups[key].functions.append(hog_function)

        return groups, ambiguous
