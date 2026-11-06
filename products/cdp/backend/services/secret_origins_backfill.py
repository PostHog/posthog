"""Bind every stored secret input of a hog function to the origins its code can send it to.

A secret saved before the API bound secrets has no `allowed_origins`. This fills it in for the live
secrets from the live config. An entry that already has `allowed_origins` stays as it is, so a rerun
changes nothing.

A function saved before inputs were encrypted still holds its secret in plaintext `inputs`. The backfill
moves that secret into `encrypted_inputs` the way a save does, and binds it there.

Secrets a draft stages stay unbound. Publishing a draft and testing it with `use_draft` both take the
origins of an unbound staged secret from the live config, so binding the staged copy to the draft's
own code would let a draft move a live secret to a new host.
"""

import dataclasses
from collections import Counter
from collections.abc import Callable
from dataclasses import field
from enum import StrEnum
from typing import Any, Optional, TypeVar

from django.db import transaction
from django.db.models import Model, Q, QuerySet

import structlog

from posthog.dataclasses import frozen

from products.cdp.backend.models.hog_functions.hog_function import TYPES_WITH_JAVASCRIPT_SOURCE, HogFunction
from products.cdp.backend.secret_origins import (
    UNBOUND,
    mapping_inputs,
    parse_stored_origins,
    secret_origins,
    stored_origins,
)

logger = structlog.get_logger(__name__)

_PLANNED_FIELDS = ("id", "team_id", "template_id", "hog", "inputs", "inputs_schema", "encrypted_inputs", "mappings")
_SCANNED_FIELDS = ("id", "team_id", "template_id")


class SecretOutcome(StrEnum):
    BOUND = "bound"
    EMPTY = "empty"
    UNBOUND = "unbound"
    ALREADY_BOUND = "already_bound"
    SKIPPED = "skipped"
    # A workflow step secret whose step is gone, or whose step's template is.
    NO_STEP = "no_step"
    NO_TEMPLATE = "no_template"


@frozen
class SecretOriginsPlan:
    encrypted_inputs: Optional[dict[str, Any]]
    inputs: Optional[dict[str, Any]] = None
    outcomes: list[SecretOutcome]
    has_unbound_secret: bool


@frozen(frozen=False)
class BackfillReport:
    outcomes: Counter[SecretOutcome] = field(default_factory=Counter)
    unbound_templates: Counter[str] = field(default_factory=Counter)
    rows_to_write: int = 0
    rows_written: int = 0
    rows_failed: int = 0


_Row = TypeVar("_Row", bound=Model)


def _plaintext_secret_keys(hog_function: HogFunction) -> set[str]:
    inputs = hog_function.inputs or {}
    secrets = hog_function.encrypted_inputs or {}
    return {
        schema["key"]
        for schema in hog_function.inputs_schema or []
        if schema.get("secret") and isinstance(inputs.get(schema.get("key")), dict) and schema["key"] not in secrets
    }


def plan_secret_origins(hog_function: HogFunction) -> SecretOriginsPlan:
    secrets = hog_function.encrypted_inputs
    # The field hands back the ciphertext string when no configured key decrypts it.
    if secrets is not None and not isinstance(secrets, dict):
        return bind_unbound_secrets(secrets, "", {}, None)
    plaintext_keys = _plaintext_secret_keys(hog_function)
    if not plaintext_keys:
        return bind_unbound_secrets(secrets, hog_function.hog or "", hog_function.inputs or {}, hog_function.mappings)
    # Like `move_secret_inputs` on save, limited to these keys: that helper also rewrites every other
    # input to match the schema, which a backfill must not do.
    inputs = hog_function.inputs or {}
    moved_inputs = {key: value for key, value in inputs.items() if key not in plaintext_keys}
    moved_secrets = {**(secrets or {}), **{key: inputs[key] for key in plaintext_keys}}
    plan = bind_unbound_secrets(moved_secrets, hog_function.hog or "", moved_inputs, hog_function.mappings)
    return dataclasses.replace(plan, encrypted_inputs=plan.encrypted_inputs or moved_secrets, inputs=moved_inputs)


def bind_unbound_secrets(secrets: Any, hog: str, plain_inputs: dict, mappings: Any) -> SecretOriginsPlan:
    """Bind each secret in `secrets` that has no `allowed_origins` to the origins `hog` sends it to."""
    # The field hands back the ciphertext string when no configured key decrypts it.
    if secrets is not None and not isinstance(secrets, dict):
        return SecretOriginsPlan(encrypted_inputs=None, outcomes=[SecretOutcome.SKIPPED], has_unbound_secret=False)
    if not secrets:
        return SecretOriginsPlan(encrypted_inputs=None, outcomes=[], has_unbound_secret=False)

    keys = {key for key, item in secrets.items() if isinstance(item, dict)}
    outcomes = [SecretOutcome.SKIPPED] * (len(secrets) - len(keys))
    stored = {key: parse_stored_origins(secrets[key].get("allowed_origins")) for key in keys}
    unbound_keys = {key for key in keys if stored[key] is None}
    outcomes += [SecretOutcome.ALREADY_BOUND] * (len(keys) - len(unbound_keys))
    has_unbound_secret = any(origins is UNBOUND for origins in stored.values())
    if not unbound_keys:
        return SecretOriginsPlan(encrypted_inputs=None, outcomes=outcomes, has_unbound_secret=has_unbound_secret)

    derived = secret_origins(hog, {**plain_inputs, **secrets}, mapping_inputs(mappings), keys)
    updated = dict(secrets)
    for key in sorted(unbound_keys):
        origins = derived[key]
        if origins is UNBOUND:
            outcomes.append(SecretOutcome.UNBOUND)
            has_unbound_secret = True
        else:
            outcomes.append(SecretOutcome.BOUND if origins else SecretOutcome.EMPTY)
        updated[key] = {**secrets[key], "allowed_origins": stored_origins(origins)}
    return SecretOriginsPlan(encrypted_inputs=updated, outcomes=outcomes, has_unbound_secret=has_unbound_secret)


def commit_secret_origins(hog_function_id: Any, team_id: int) -> Optional[SecretOriginsPlan]:
    with transaction.atomic():
        locked = (
            HogFunction.objects.select_for_update()
            .only(*_PLANNED_FIELDS)
            .filter(pk=hog_function_id, team_id=team_id, deleted=False)
            .first()
        )
        if locked is None:
            return None
        plan = plan_secret_origins(locked)
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
    return run_backfill(queryset, lambda hog_function, report: _backfill_row(hog_function, commit, report), batch_size)


def run_backfill(
    queryset: QuerySet[_Row], backfill_row: Callable[[_Row, BackfillReport], None], batch_size: int
) -> BackfillReport:
    """Run `backfill_row` on each row, counting a row that raises as failed and carrying on."""
    report = BackfillReport()
    rows_scanned = 0
    last_id = None
    # Keyset pages, because `.iterator()` behind pgbouncer has no server-side cursor and loads every row.
    while batch := list((queryset if last_id is None else queryset.filter(id__gt=last_id))[:batch_size]):
        for row in batch:
            try:
                backfill_row(row, report)
            except Exception as error:
                # Never log the exception itself: its message or traceback can carry decrypted values.
                logger.warning(
                    "secret_origins_backfill_row_failed",
                    model=type(row).__name__,
                    row_id=str(row.pk),
                    error_type=type(error).__name__,
                )
                report.rows_failed += 1
        last_id = batch[-1].pk
        rows_scanned += len(batch)
        _log_progress(rows_scanned, report)
    return report


def _backfill_row(hog_function: HogFunction, commit: bool, report: BackfillReport) -> None:
    if commit:
        locked_plan = commit_secret_origins(hog_function.pk, hog_function.team_id)
        if locked_plan is None:
            return
        plan = locked_plan
        if plan.encrypted_inputs is not None:
            report.rows_written += 1
    else:
        plan = plan_secret_origins(hog_function)
        if plan.encrypted_inputs is not None:
            report.rows_to_write += 1
    report.outcomes.update(plan.outcomes)
    if plan.has_unbound_secret:
        report.unbound_templates[hog_function.template_id or "(none)"] += 1


def _log_progress(rows_scanned: int, report: BackfillReport) -> None:
    logger.info(
        "secret_origins_backfill_progress",
        rows_scanned=rows_scanned,
        rows_written=report.rows_written,
        rows_failed=report.rows_failed,
    )
