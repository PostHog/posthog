"""Store the origins each legacy secret input of a hog function may be sent to.

A legacy secret is a stored secret with no bound platform `auth`, so the function's code reads its value. A secret
saved before the API stored origins has no `allowed_origins`. This fills them in from the template's `auth`
declaration for that key, or with any origin ("*") when the template declares none. Code is never read. An entry
that already has origins or a bound `auth` stays as it is, so a rerun changes nothing.

A function saved before inputs were encrypted still holds its secret in plaintext `inputs`. The backfill moves that
secret into `encrypted_inputs` the way a save does, and stores its origins there.

Secrets a draft stages stay as they are. Publishing the draft stores their origins.
"""

from collections import Counter
from dataclasses import field
from enum import StrEnum
from typing import Any, Optional

from django.db import transaction
from django.db.models import Q

import structlog

from posthog.dataclasses import frozen

from products.cdp.backend.legacy_secrets import ANY_ORIGIN, has_bound_auth, template_origins
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import TYPES_WITH_JAVASCRIPT_SOURCE, HogFunction

logger = structlog.get_logger(__name__)

_PLANNED_FIELDS = ("id", "team_id", "template_id", "inputs", "inputs_schema", "encrypted_inputs")
_SCANNED_FIELDS = ("id", "team_id", "template_id")


class SecretOutcome(StrEnum):
    DECLARED = "declared"
    ANY_ORIGIN = "any_origin"
    ALREADY_STORED = "already_stored"
    PLATFORM_AUTH = "platform_auth"
    SKIPPED = "skipped"


@frozen
class SecretOriginsPlan:
    encrypted_inputs: Optional[dict[str, Any]]
    inputs: Optional[dict[str, Any]] = None
    outcomes: list[SecretOutcome]
    has_any_origin_secret: bool


@frozen(frozen=False)
class BackfillReport:
    outcomes: Counter[SecretOutcome] = field(default_factory=Counter)
    any_origin_templates: Counter[str] = field(default_factory=Counter)
    rows_to_write: int = 0
    rows_written: int = 0
    rows_failed: int = 0


class TemplateCache:
    def __init__(self) -> None:
        self._templates: dict[str, Optional[HogFunctionTemplate]] = {}

    def get(self, template_id: Optional[str]) -> Optional[HogFunctionTemplate]:
        if not template_id:
            return None
        if template_id not in self._templates:
            self._templates[template_id] = HogFunctionTemplate.get_template(template_id)
        return self._templates[template_id]


def _plaintext_secret_keys(hog_function: HogFunction) -> set[str]:
    inputs = hog_function.inputs or {}
    secrets = hog_function.encrypted_inputs or {}
    return {
        schema["key"]
        for schema in hog_function.inputs_schema or []
        if schema.get("secret") and isinstance(inputs.get(schema.get("key")), dict) and schema["key"] not in secrets
    }


def _has_stored_origins(entry: dict) -> bool:
    origins = entry.get("allowed_origins")
    return origins == ANY_ORIGIN or (isinstance(origins, list) and all(isinstance(o, str) for o in origins))


def plan_secret_origins(hog_function: HogFunction, template: Optional[HogFunctionTemplate]) -> SecretOriginsPlan:
    # The field hands back the ciphertext string when no configured key decrypts it.
    if hog_function.encrypted_inputs is not None and not isinstance(hog_function.encrypted_inputs, dict):
        return SecretOriginsPlan(encrypted_inputs=None, outcomes=[SecretOutcome.SKIPPED], has_any_origin_secret=False)

    inputs = hog_function.inputs or {}
    secrets = hog_function.encrypted_inputs or {}
    moved_inputs: Optional[dict[str, Any]] = None
    if plaintext_keys := _plaintext_secret_keys(hog_function):
        # Like `move_secret_inputs` on save, limited to these keys: that helper also rewrites every other
        # input to match the schema, which a backfill must not do.
        moved_inputs = {key: value for key, value in inputs.items() if key not in plaintext_keys}
        secrets = {**secrets, **{key: inputs[key] for key in plaintext_keys}}

    updated = dict(secrets)
    outcomes: list[SecretOutcome] = []
    has_any_origin_secret = False
    for key in sorted(secrets):
        entry = secrets[key]
        if not isinstance(entry, dict):
            outcomes.append(SecretOutcome.SKIPPED)
        elif has_bound_auth(entry):
            outcomes.append(SecretOutcome.PLATFORM_AUTH)
        elif _has_stored_origins(entry):
            outcomes.append(SecretOutcome.ALREADY_STORED)
            has_any_origin_secret |= entry["allowed_origins"] == ANY_ORIGIN
        else:
            origins = template_origins(template, key, moved_inputs if moved_inputs is not None else inputs)
            outcomes.append(SecretOutcome.ANY_ORIGIN if origins == ANY_ORIGIN else SecretOutcome.DECLARED)
            has_any_origin_secret |= origins == ANY_ORIGIN
            updated[key] = {**entry, "allowed_origins": origins}

    changed = moved_inputs is not None or updated != secrets
    return SecretOriginsPlan(
        encrypted_inputs=updated if changed else None,
        inputs=moved_inputs,
        outcomes=outcomes,
        has_any_origin_secret=has_any_origin_secret,
    )


def commit_secret_origins(hog_function_id: Any, team_id: int, templates: TemplateCache) -> Optional[SecretOriginsPlan]:
    with transaction.atomic():
        locked = (
            HogFunction.objects.select_for_update()
            .only(*_PLANNED_FIELDS)
            .filter(pk=hog_function_id, team_id=team_id, deleted=False)
            .first()
        )
        if locked is None:
            return None
        plan = plan_secret_origins(locked, templates.get(locked.template_id))
        if plan.encrypted_inputs is not None:
            # `update` writes only the input columns: `save` would recompile filters and push a reload,
            # and it would move `updated_at`, which a pending publish confirmation signs. The worker reads
            # a secret from `inputs` or `encrypted_inputs` alike, so a moved secret needs no reload.
            columns: dict[str, Any] = {"encrypted_inputs": plan.encrypted_inputs}
            if plan.inputs is not None:
                columns["inputs"] = plan.inputs
            HogFunction.objects.filter(pk=hog_function_id, team_id=team_id).update(**columns)
    return plan


def backfill_secret_origins(*, commit: bool, team_id: Optional[int] = None, batch_size: int = 500) -> BackfillReport:
    queryset = (
        HogFunction.objects.filter(
            Q(encrypted_inputs__isnull=False) | Q(inputs_schema__contains=[{"secret": True}]), deleted=False
        )
        .exclude(type__in=TYPES_WITH_JAVASCRIPT_SOURCE)
        .only(*(_SCANNED_FIELDS if commit else _PLANNED_FIELDS))
        .order_by("id")
    )
    if team_id is not None:
        queryset = queryset.filter(team_id=team_id)

    report = BackfillReport()
    templates = TemplateCache()
    rows_scanned = 0
    last_id = None
    # Keyset pages, because `.iterator()` behind pgbouncer has no server-side cursor and loads every row.
    while batch := list((queryset if last_id is None else queryset.filter(id__gt=last_id))[:batch_size]):
        for hog_function in batch:
            try:
                _backfill_row(hog_function, commit, report, templates)
            except Exception as error:
                # Never log the exception itself: its message or traceback can carry decrypted values.
                logger.warning(
                    "secret_origins_backfill_row_failed",
                    hog_function_id=str(hog_function.pk),
                    error_type=type(error).__name__,
                )
                report.rows_failed += 1
        last_id = batch[-1].pk
        rows_scanned += len(batch)
        _log_progress(rows_scanned, report)
    return report


def _backfill_row(hog_function: HogFunction, commit: bool, report: BackfillReport, templates: TemplateCache) -> None:
    if commit:
        locked_plan = commit_secret_origins(hog_function.pk, hog_function.team_id, templates)
        if locked_plan is None:
            return
        plan = locked_plan
        if plan.encrypted_inputs is not None:
            report.rows_written += 1
    else:
        plan = plan_secret_origins(hog_function, templates.get(hog_function.template_id))
        if plan.encrypted_inputs is not None:
            report.rows_to_write += 1
    report.outcomes.update(plan.outcomes)
    if plan.has_any_origin_secret:
        report.any_origin_templates[hog_function.template_id or "(none)"] += 1


def _log_progress(rows_scanned: int, report: BackfillReport) -> None:
    logger.info(
        "secret_origins_backfill_progress",
        rows_scanned=rows_scanned,
        rows_written=report.rows_written,
        rows_failed=report.rows_failed,
    )
