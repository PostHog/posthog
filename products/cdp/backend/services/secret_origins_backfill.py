"""Bind every stored secret input of a hog function to the origins its code can send it to.

A secret saved before the API bound secrets has no `allowed_origins`. This fills it in for the live
secrets and the secrets a draft stages, from the config each one runs with. An entry that already
has `allowed_origins` stays as it is, so a rerun changes nothing.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

from django.db import transaction
from django.db.models import Q

from posthog.dataclasses import frozen

from products.cdp.backend.models.hog_functions.hog_function import TYPES_WITH_JAVASCRIPT_SOURCE, HogFunction
from products.cdp.backend.secret_origins import UNBOUND, secret_origins, stored_origins

LIVE = "live"
STAGED = "staged"
# A save between the scan and the write can change any of these, and with them the derived origins.
_SCANNED_FIELDS = (
    "type",
    "deleted",
    "hog",
    "inputs",
    "encrypted_inputs",
    "mappings",
    "draft",
    "draft_encrypted_inputs",
)


@frozen
class SecretOriginsPlan:
    hog_function: HogFunction
    changes: dict[str, dict[str, Any]]
    outcomes: list[tuple[str, str]]


@dataclass(frozen=False)
class BackfillReport:
    outcomes: Counter[tuple[str, str]] = field(default_factory=Counter)
    unbound_templates: Counter[str] = field(default_factory=Counter)
    rows_to_write: int = 0
    rows_written: int = 0
    rows_changed: int = 0


def _mapping_inputs(mappings: Any) -> list[dict]:
    return [mapping.get("inputs") or {} for mapping in mappings or [] if isinstance(mapping, dict)]


def _bind(
    secrets: Any, hog: Optional[str], plain_inputs: dict, mappings: Any, store: str, outcomes: list[tuple[str, str]]
) -> Optional[dict[str, Any]]:
    if not secrets:
        return None
    # The field hands back the ciphertext string when no configured key decrypts it.
    if not isinstance(secrets, dict):
        outcomes.append((store, "skipped"))
        return None
    keys = {key for key, item in secrets.items() if isinstance(item, dict)}
    outcomes += [(store, "skipped")] * (len(secrets) - len(keys))
    unbound_keys = {key for key in keys if "allowed_origins" not in secrets[key]}
    outcomes += [(store, "already_bound")] * (len(keys) - len(unbound_keys))
    if not unbound_keys:
        return None

    derived = secret_origins(hog or "", {**plain_inputs, **secrets}, _mapping_inputs(mappings), keys)
    updated = dict(secrets)
    for key in sorted(unbound_keys):
        origins = derived[key]
        outcomes.append((store, "unbound" if origins is UNBOUND else "bound" if origins else "empty"))
        updated[key] = {**secrets[key], "allowed_origins": stored_origins(origins)}
    return updated


def plan_secret_origins(hog_function: HogFunction) -> SecretOriginsPlan:
    outcomes: list[tuple[str, str]] = []
    live_secrets = hog_function.encrypted_inputs
    changes: dict[str, dict[str, Any]] = {}
    live = _bind(live_secrets, hog_function.hog, hog_function.inputs or {}, hog_function.mappings, LIVE, outcomes)
    if live is not None:
        changes["encrypted_inputs"] = live

    # Built the way the API builds a draft: the live config with the staged fields on top.
    draft = {
        "hog": hog_function.hog,
        "inputs": hog_function.inputs,
        "mappings": hog_function.mappings,
        **(hog_function.draft or {}),
    }
    draft_inputs = {**(draft.get("inputs") or {}), **(live_secrets if isinstance(live_secrets, dict) else {})}
    staged = _bind(
        hog_function.draft_encrypted_inputs, draft.get("hog"), draft_inputs, draft.get("mappings"), STAGED, outcomes
    )
    if staged is not None:
        changes["draft_encrypted_inputs"] = staged
    return SecretOriginsPlan(hog_function=hog_function, changes=changes, outcomes=outcomes)


def apply_secret_origins(plan: SecretOriginsPlan) -> bool:
    scanned = plan.hog_function
    with transaction.atomic():
        current = (
            HogFunction.objects.select_for_update()
            .only("id", *_SCANNED_FIELDS)
            .get(pk=scanned.pk, team_id=scanned.team_id)
        )
        if any(getattr(current, name) != getattr(scanned, name) for name in _SCANNED_FIELDS):
            return False
        # `update` writes only the encrypted columns: `save` would re-split inputs, recompile filters
        # and push a reload, and it would move `updated_at`, which a pending publish confirmation signs.
        HogFunction.objects.filter(pk=scanned.pk, team_id=scanned.team_id).update(**plan.changes)
    return True


def backfill_secret_origins(*, apply: bool, team_id: Optional[int] = None, batch_size: int = 500) -> BackfillReport:
    queryset = (
        HogFunction.objects.filter(deleted=False)
        .exclude(type__in=TYPES_WITH_JAVASCRIPT_SOURCE)
        .filter(Q(encrypted_inputs__isnull=False) | Q(draft_encrypted_inputs__isnull=False))
    )
    if team_id is not None:
        queryset = queryset.filter(team_id=team_id)

    report = BackfillReport()
    ids = list(queryset.order_by("id").values_list("id", flat=True))
    for start in range(0, len(ids), batch_size):
        batch = queryset.filter(id__in=ids[start : start + batch_size]).only(
            "id", "team_id", "template_id", *_SCANNED_FIELDS
        )
        for hog_function in batch:
            plan = plan_secret_origins(hog_function)
            report.outcomes.update(plan.outcomes)
            report.unbound_templates.update(
                hog_function.template_id or "(none)" for _, outcome in plan.outcomes if outcome == "unbound"
            )
            if not plan.changes:
                continue
            report.rows_to_write += 1
            if apply and apply_secret_origins(plan):
                report.rows_written += 1
            elif apply:
                report.rows_changed += 1
    return report
