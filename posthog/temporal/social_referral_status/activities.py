"""Social referral referee status stages — ingestion signal from Postgres."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog
from temporalio import activity

from posthog.models import SocialReferral, Team
from posthog.models.social_referral import REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY, REFEREE_STATE_ERRORS_KEY
from posthog.sync import database_sync_to_async
from posthog.temporal.social_referral_status.types import (
    ProcessSingleReferralIngestionInput,
    RecordIngestionCheckFailureInput,
)

FIRST_EVENT_SENT_KEY = "first_event_sent"
INGESTION_CHECK_FAILURE_DETAIL_MAX_LEN = 4000

_LOGGER = structlog.get_logger(__name__)


def referee_entry_pending_first_event(entry: object) -> bool:
    """True unless `first_event_sent` is explicitly true."""
    if not isinstance(entry, dict):
        return True
    return entry.get(FIRST_EVENT_SENT_KEY) is not True


def _is_reserved_referee_state_key(org_key: str) -> bool:
    return org_key == REFEREE_STATE_ERRORS_KEY


def _clear_ingestion_sync_error_from_merged(merged: dict[str, Any]) -> bool:
    """Remove ``errors.ingestion_sync``; drop ``errors`` if empty. Returns whether ``merged`` changed."""
    errors_raw = merged.get(REFEREE_STATE_ERRORS_KEY)
    if not isinstance(errors_raw, dict) or REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY not in errors_raw:
        return False
    err = dict(errors_raw)
    del err[REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY]
    if err:
        merged[REFEREE_STATE_ERRORS_KEY] = err
    else:
        merged.pop(REFEREE_STATE_ERRORS_KEY, None)
    return True


def record_ingestion_check_failure_on_referral_sync(referral_id: UUID, error_detail: str) -> bool:
    """Write last ingestion activity failure under ``referee_state.errors.ingestion_sync``."""
    detail = error_detail[:INGESTION_CHECK_FAILURE_DETAIL_MAX_LEN]
    with transaction.atomic():
        referral = SocialReferral.objects.select_for_update().filter(id=referral_id).first()
        if referral is None:
            return False
        merged = dict(referral.referee_state) if isinstance(referral.referee_state, dict) else {}
        errors: dict[str, Any] = {}
        existing_errors = merged.get(REFEREE_STATE_ERRORS_KEY)
        if isinstance(existing_errors, dict):
            errors = dict(existing_errors)
        errors[REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY] = {
            "last_failure_at": timezone.now().isoformat(),
            "last_failure_detail": detail,
        }
        merged[REFEREE_STATE_ERRORS_KEY] = errors
        referral.referee_state = merged
        referral.save(update_fields=["referee_state"])
    return True


def _compute_org_level_diagnostics(referee_org_to_row_ids: dict[str, list[UUID]]) -> dict[str, int]:
    org_keys_evaluated_valid = 0
    org_skipped_invalid_uuid = 0
    referee_orgs_without_teams = 0
    for org_uuid_str in referee_org_to_row_ids:
        try:
            org_uuid = UUID(org_uuid_str)
        except ValueError:
            org_skipped_invalid_uuid += 1
            _LOGGER.warning(
                "social_referral_status_invalid_org_uuid_referee_state",
                org_key_prefix=org_uuid_str[:64],
            )
            continue
        org_keys_evaluated_valid += 1
        if not Team.objects.filter(organization_id=org_uuid).exists():
            referee_orgs_without_teams += 1
    return {
        "org_keys_evaluated_valid": org_keys_evaluated_valid,
        "org_skipped_invalid_uuid": org_skipped_invalid_uuid,
        "referee_orgs_without_teams": referee_orgs_without_teams,
    }


def build_pending_ingestion_snapshot() -> dict[str, Any]:
    """Build org index, org-level pre-checks, and referral ids that still have pending entries."""
    referee_org_to_row_ids: dict[str, list[UUID]] = {}
    referral_ids_with_any_pending: set[UUID] = set()

    qs = SocialReferral.objects.only("id", "referee_state").iterator(chunk_size=500)

    for row in qs:
        state = row.referee_state if isinstance(row.referee_state, dict) else {}
        row_id = row.id
        row_has_pending = False
        for org_key, payload in state.items():
            if not isinstance(org_key, str):
                continue
            if _is_reserved_referee_state_key(org_key):
                continue
            if not referee_entry_pending_first_event(payload):
                continue
            row_has_pending = True
            referee_org_to_row_ids.setdefault(org_key, []).append(row_id)
        if row_has_pending:
            referral_ids_with_any_pending.add(row_id)

    org_diag = _compute_org_level_diagnostics(referee_org_to_row_ids)

    referral_ids = sorted(str(rid) for rid in referral_ids_with_any_pending)

    return {
        "referral_ids": referral_ids,
        "pending_referee_org_count": len(referee_org_to_row_ids),
        **org_diag,
    }


def process_single_social_referral_ingestion_sync(referral_id: UUID) -> dict[str, int]:
    """Apply ingestion checks for one SocialReferral; isolate failures to this row."""
    orgs_flipped = 0
    with transaction.atomic():
        referral = SocialReferral.objects.select_for_update().filter(id=referral_id).first()
        if referral is None:
            return {"orgs_flipped": 0}

        merged = dict(referral.referee_state) if isinstance(referral.referee_state, dict) else {}
        changed = False

        if _clear_ingestion_sync_error_from_merged(merged):
            changed = True

        for org_key, payload in list(merged.items()):
            if not isinstance(org_key, str):
                continue
            if _is_reserved_referee_state_key(org_key):
                continue
            if not referee_entry_pending_first_event(payload):
                continue
            try:
                org_uuid = UUID(org_key)
            except ValueError:
                continue
            if not Team.objects.filter(organization_id=org_uuid).exists():
                continue
            if not Team.objects.filter(organization_id=org_uuid, ingested_event=True).exists():
                continue

            entry_raw = merged.get(org_key)
            if isinstance(entry_raw, dict) and entry_raw.get(FIRST_EVENT_SENT_KEY) is True:
                continue
            if isinstance(entry_raw, dict):
                merged[org_key] = {**entry_raw, FIRST_EVENT_SENT_KEY: True}
            else:
                merged[org_key] = {FIRST_EVENT_SENT_KEY: True}
            orgs_flipped += 1
            changed = True

            # TODO(referrals): downstream notification/email when ingestion stage clears for this referrer row + org pair

        if changed:
            referral.referee_state = merged
            referral.save(update_fields=["referee_state"])

    return {"orgs_flipped": orgs_flipped}


def execute_referral_ingestion_stage_sweep() -> dict[str, int]:
    """Full scan (single process) — used by tests and emergency/manual runs."""
    snapshot = build_pending_ingestion_snapshot()
    total_orgs_flipped = 0
    for rid_str in snapshot["referral_ids"]:
        total_orgs_flipped += process_single_social_referral_ingestion_sync(UUID(rid_str))["orgs_flipped"]

    summary: dict[str, int] = {
        "pending_referee_org_count": snapshot["pending_referee_org_count"],
        "org_keys_evaluated_valid": snapshot["org_keys_evaluated_valid"],
        "org_skipped_invalid_uuid": snapshot["org_skipped_invalid_uuid"],
        "referee_orgs_without_teams": snapshot["referee_orgs_without_teams"],
        "referees_rows_updated": total_orgs_flipped,
    }

    _LOGGER.info("social_referral_status_ingestion_sweep_finished", summary=summary)
    return summary


@activity.defn(name="referral-status-list-pending-ingestion")
async def referral_status_list_pending_ingestion_activity() -> dict[str, Any]:
    @database_sync_to_async(thread_sensitive=True)
    def django_sync() -> dict[str, Any]:
        return build_pending_ingestion_snapshot()

    return await django_sync()


@activity.defn(name="referral-status-process-single-ingestion")
async def referral_status_process_single_ingestion_activity(inp: ProcessSingleReferralIngestionInput):
    @database_sync_to_async(thread_sensitive=True)
    def django_sync() -> dict[str, int]:
        return process_single_social_referral_ingestion_sync(UUID(inp.social_referral_id))

    return await django_sync()


@activity.defn(name="referral-status-record-ingestion-check-failure")
async def referral_status_record_ingestion_check_failure_activity(inp: RecordIngestionCheckFailureInput) -> bool:
    @database_sync_to_async(thread_sensitive=True)
    def django_sync() -> bool:
        return record_ingestion_check_failure_on_referral_sync(UUID(inp.social_referral_id), inp.error_detail)

    return await django_sync()
