"""Metric write path and approval lifecycle.

Names are unique among a team's live metrics: creating with a live existing name refines that metric,
while creating with a deleted metric's name starts a fresh one (delete and rename free the name for
reuse). A metric can be created from an insight
(its query is snapshotted server-side and drift is flagged for re-review). Promotion to ``approved``
is blocked while a metric is drifted. All transitions emit capture events for success-criteria
measurement.
"""

import re
from functools import partial
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.scoping import team_scope
from posthog.rbac.user_access_control import UserAccessControl

from products.product_analytics.backend.facade.models import Insight

from ..facade.enums import CreatedSource, MetricStatus
from ..models import METRIC_NAME_REGEX, Metric
from .analytics import (
    METRIC_APPROVAL_BLOCKED_EVENT,
    METRIC_APPROVED_EVENT,
    METRIC_CREATED_EVENT,
    METRIC_DELETED_EVENT,
    METRIC_UPDATED_EVENT,
    capture_metric_event,
)
from .drift import canonical_query_hash, compute_drift, effective_insight_query, fetch_insight
from .exceptions import MetricDrifted, SourceInsightUnavailable
from .validation import validate_description, validate_metric_definition

if TYPE_CHECKING:
    from rest_framework.request import Request


class _Unset:
    """Sentinel for upsert fields the caller did not supply: kept as-is on refine, defaulted on create.

    A plain ``None`` default cannot express this because ``None`` is a legitimate value for
    ``definition``/``confidence``/``owner`` (an explicit clear), distinct from "not provided".
    """


_UNSET = _Unset()

# The columns _reset_to_proposed touches, so a lifecycle reset can be scoped into update_fields.
_APPROVAL_FIELDS = frozenset({"status", "approved_by", "approved_at"})

# Fields that carry the metric's reviewed meaning: editing any of them invalidates a prior approval.
# The definition is compared by canonical hash separately; these are compared by value. display_name
# (a cosmetic label), owner, and provenance metadata are not part of what a reviewer blessed.
# name is in here because agents pick a metric by matching its name (see the information_schema.metrics
# description), so moving an approved definition under a different name changes what the approval says.
_APPROVAL_RELEVANT_FIELDS = frozenset({"name", "description", "unit"})

# One bulk request holds a row lock per metric for the length of a single transaction, so the batch
# is capped. A team's catalog is tens of metrics, well inside this.
METRIC_BULK_MAX = 100

BULK_SKIP_NOT_FOUND = "Not found"
BULK_SKIP_ALREADY_APPROVED = "Already approved"
BULK_SKIP_DRIFTED = "Drifted from its source insight"


@frozen
class MetricBulkSkip:
    """A metric a bulk operation did not act on, and why."""

    name: str
    reason: str


def _canonical_definition(
    definition: Optional[dict], team: Team, user: Optional[User]
) -> tuple[Optional[dict], list[str]]:
    if definition is None:
        return None, []
    return validate_metric_definition(definition, team, user)


def _require_insight_viewer_access(insight: Insight, team: Team, user: Optional[User]) -> None:
    """Gate snapshotting an insight's query on per-object viewer access.

    Team scoping alone doesn't enforce object-level insight access controls, so a caller with
    catalog write access could otherwise read a restricted insight's query back out of the metric.
    System/agent callers (``user`` is None) are already trusted and bypass this.
    """
    if user is None:
        return
    if not UserAccessControl(user=user, team=team).check_access_level_for_object(insight, "viewer"):
        raise ValidationError({"source_insight_short_id": "You do not have access to this insight."})


def _snapshot_from_insight(team: Team, short_id: str, user: Optional[User]) -> tuple[dict, str]:
    """Snapshot a live insight's query and its canonical hash for drift tracking."""
    insight = fetch_insight(team.id, short_id)
    if insight is None:
        raise ValidationError({"source_insight_short_id": "Insight not found."})
    _require_insight_viewer_access(insight, team, user)
    query = effective_insight_query(insight)
    if not query:
        raise ValidationError(
            {"source_insight_short_id": "Could not convert this insight's query. Define the metric manually."}
        )
    return query, canonical_query_hash(query)


def _resolve_definition_fields(
    definition: dict | None | _Unset,
    source_insight_short_id: str | None | _Unset,
    team: Team,
    user: Optional[User],
) -> dict[str, object]:
    """Derive the definition / insight-link fields to write, honoring the definition-XOR-insight rule.

    Returns only the keys the caller actually engaged, so a refine that supplies neither writes
    nothing (leaving a stored definition and its insight link untouched). A supplied definition
    validates, extracts referenced tables, and unlinks any source insight; a non-empty insight id
    snapshots the query; a supplied-but-empty insight id clears the link and its snapshot hash.
    """
    insight_supplied = not isinstance(source_insight_short_id, _Unset)

    if not isinstance(source_insight_short_id, _Unset) and source_insight_short_id:
        if not isinstance(definition, _Unset) and definition is not None:
            raise ValidationError({"definition": "Provide a definition or a source insight, not both."})
        snapshot_def, snapshot_hash = _snapshot_from_insight(team, source_insight_short_id, user)
        canonical_def, referenced = _canonical_definition(snapshot_def, team, user)
        return {
            "definition": canonical_def,
            "referenced_table_names": referenced,
            "source_insight_short_id": source_insight_short_id,
            "source_insight_query_hash": snapshot_hash,
        }

    result: dict[str, object] = {}
    if not isinstance(definition, _Unset):
        canonical_def, referenced = _canonical_definition(definition, team, user)
        result["definition"] = canonical_def
        result["referenced_table_names"] = referenced
        result["source_insight_short_id"] = None
        result["source_insight_query_hash"] = None

    if insight_supplied:
        # Supplied but empty (the truthy case returned above): unlink and drop the snapshot hash.
        result["source_insight_short_id"] = None
        result["source_insight_query_hash"] = None

    return result


def _definition_hash(definition: Optional[dict]) -> Optional[str]:
    return canonical_query_hash(definition) if definition else None


def _invalidates_approval(metric: Metric, fields: dict) -> bool:
    """True if this write changes the metric's reviewed meaning (definition, description, or unit).

    Compares the incoming ``fields`` against ``metric``'s current (pre-mutation) values. For a
    definition-less metric the description is the entire meaningful definition, so a description or
    unit edit — reachable with catalog write access alone — must reset approval just as a definition
    edit does.

    Changing the source-insight link (unlink or relink) while the metric is drifted also
    invalidates: it would erase the drift signal that flags the approval as stale, laundering an
    outdated approval into "approved and current". Unlinking an in-sync metric keeps approval — the
    blessed definition is unchanged and was in lockstep when tracking stopped.
    """
    if "definition" in fields and _definition_hash(fields["definition"]) != _definition_hash(metric.definition):
        return True
    if (
        "source_insight_short_id" in fields
        and fields["source_insight_short_id"] != metric.source_insight_short_id
        and metric.status == MetricStatus.APPROVED
        and compute_drift([metric])[metric.id]
    ):
        return True
    return any(key in fields and fields[key] != getattr(metric, key) for key in _APPROVAL_RELEVANT_FIELDS)


def _refine(metric: Metric, fields: dict) -> None:
    if _invalidates_approval(metric, fields):
        # Refining an approved metric's meaning (definition, description, or unit) changes what it
        # computes or how it reads; its review no longer holds, so drop back to proposed (matching
        # update_metric's PATCH behavior).
        _reset_to_proposed(metric)
    for key, value in fields.items():
        setattr(metric, key, value)
    metric.save()


def upsert_metric(
    *,
    team: Team,
    user: Optional[User],
    name: str,
    description: str,
    display_name: str | _Unset = _UNSET,
    unit: str | _Unset = _UNSET,
    owner: User | None | _Unset = _UNSET,
    definition: dict | None | _Unset = _UNSET,
    source_insight_short_id: str | None | _Unset = _UNSET,
    created_source: CreatedSource | _Unset = _UNSET,
    ai_model: str | _Unset = _UNSET,
    confidence: float | None | _Unset = _UNSET,
    reasoning: str | _Unset = _UNSET,
    request: "Request | None" = None,
) -> Metric:
    """Create a metric, or refine the live one already holding ``name`` for this team.

    Refine is a partial merge: only the fields the caller supplies are written, so a refine that
    omits a field leaves that field (a stored ``definition``, provenance, ...) untouched rather than
    resetting it. On create, omitted fields fall back to the model defaults (``owner`` to ``user``).

    Accepts a ``definition`` XOR a ``source_insight_short_id`` (create-from-insight snapshots the
    insight's query server-side). Always lands ``proposed``.
    """
    if not re.match(METRIC_NAME_REGEX, name or ""):
        raise ValidationError(
            {"name": "Name must start with a letter and contain only letters, numbers, and underscores."}
        )
    validate_description(description)

    fields: dict[str, object] = {"description": description}
    for key, value in (
        ("display_name", display_name),
        ("unit", unit),
        ("owner", owner),
        ("created_source", created_source),
        ("ai_model", ai_model),
        ("confidence", confidence),
        ("reasoning", reasoning),
    ):
        if not isinstance(value, _Unset):
            fields[key] = value

    fields.update(_resolve_definition_fields(definition, source_insight_short_id, team, user))

    # team_scope so the ModelActivityMixin's before-update lookup (via the fail-closed manager)
    # works regardless of caller context (viewset, Celery, MCP, tests).
    with team_scope(team.id):
        try:
            with transaction.atomic():
                existing = Metric.objects.for_team(team.id).filter(name=name, deleted=False).select_for_update().first()
                created = existing is None
                if existing is not None:
                    _refine(existing, fields)
                    metric = existing
                else:
                    metric = Metric.objects.for_team(team.id).create(
                        team=team,
                        name=name,
                        created_by=user,
                        status=MetricStatus.PROPOSED,
                        **{"owner": user, **fields},
                    )
        except IntegrityError:
            # A concurrent writer created (team, name) first; refine that row instead of failing.
            with transaction.atomic():
                existing = Metric.objects.for_team(team.id).filter(name=name, deleted=False).select_for_update().first()
                if existing is None:
                    raise
                _refine(existing, fields)
                metric, created = existing, False

    capture_metric_event(
        METRIC_CREATED_EVENT if created else METRIC_UPDATED_EVENT, metric, team=team, user=user, request=request
    )
    return metric


def update_metric(
    metric: Metric, *, team: Team, user: Optional[User], request: "Request | None" = None, **fields
) -> Metric:
    """Partially update a metric. Renaming frees the old name; editing an approved definition resets approval."""
    if fields.get("name") == metric.name:
        fields.pop("name")
    renamed_from = metric.name if "name" in fields else None
    if renamed_from is not None:
        if not re.match(METRIC_NAME_REGEX, fields["name"] or ""):
            raise ValidationError(
                {"name": "Name must start with a letter and contain only letters, numbers, and underscores."}
            )
        if Metric.objects.for_team(team.id).filter(name=fields["name"], deleted=False).exclude(pk=metric.pk).exists():
            raise ValidationError({"name": "A metric with this name already exists."})
    if "description" in fields:
        validate_description(fields["description"])

    # Route definition / insight-link through the same resolver as create, so a PATCH honors the
    # definition-XOR-insight rule, snapshots (and validates) on relink, and drops the hash on unlink.
    definition_arg = fields.pop("definition", _UNSET)
    source_insight_arg = fields.pop("source_insight_short_id", _UNSET)
    fields.update(_resolve_definition_fields(definition_arg, source_insight_arg, team, user))

    try:
        with team_scope(team.id), transaction.atomic():
            metric = Metric.objects.for_team(team.id).select_for_update().get(pk=metric.pk)
            approval_invalidated = _invalidates_approval(metric, fields)

            for key, value in fields.items():
                setattr(metric, key, value)

            changed_fields = set(fields.keys())
            if approval_invalidated and metric.status == MetricStatus.APPROVED:
                # The edit changed what the metric means, so its approval no longer holds.
                _reset_to_proposed(metric)
                changed_fields |= _APPROVAL_FIELDS

            metric.save(update_fields=[*changed_fields, "updated_at"])
    except IntegrityError:
        # A concurrent writer claimed the target name between the pre-check and the save (the row
        # lock is on this metric, not on the name).
        if renamed_from is None:
            raise
        raise ValidationError({"name": "A metric with this name already exists."})
    capture_metric_event(
        METRIC_UPDATED_EVENT,
        metric,
        team=team,
        user=user,
        request=request,
        extra={"renamed_from": renamed_from} if renamed_from else None,
    )
    return metric


def _apply_approval(metric: Metric, user: Optional[User]) -> None:
    metric.status = MetricStatus.APPROVED
    metric.approved_by = user
    metric.approved_at = timezone.now()
    metric.save(update_fields=[*_APPROVAL_FIELDS, "updated_at"])


def approve_metric(metric: Metric, user: Optional[User], request: "Request | None" = None) -> Metric:
    """Bless a metric as canonical. Blocked (409) while drifted. Idempotent on an already-approved metric."""
    with team_scope(metric.team_id), transaction.atomic():
        metric = Metric.objects.for_team(metric.team_id).select_for_update().get(pk=metric.pk)
        if compute_drift([metric])[metric.id]:
            capture_metric_event(
                METRIC_APPROVAL_BLOCKED_EVENT,
                metric,
                team=metric.team,
                user=user,
                request=request,
                extra={"reason": "drifted"},
            )
            raise MetricDrifted()
        if metric.status == MetricStatus.APPROVED:
            return metric
        _apply_approval(metric, user)
    capture_metric_event(METRIC_APPROVED_EVENT, metric, team=metric.team, user=user, request=request)
    return metric


def refresh_metric_from_insight(metric: Metric, user: Optional[User], request: "Request | None" = None) -> Metric:
    """Re-snapshot the linked insight's current query; a changed definition resets approval."""
    with team_scope(metric.team_id), transaction.atomic():
        metric = Metric.objects.for_team(metric.team_id).select_for_update().get(pk=metric.pk)
        if not metric.source_insight_short_id:
            raise ValidationError({"source_insight_short_id": "This metric is not linked to an insight."})

        insight = fetch_insight(metric.team_id, metric.source_insight_short_id, include_deleted=True)
        if insight is None or insight.deleted:
            raise SourceInsightUnavailable()
        _require_insight_viewer_access(insight, metric.team, user)
        query = effective_insight_query(insight)
        if not query:
            raise SourceInsightUnavailable(
                "Could not convert the source insight's query. Edit the definition or unlink."
            )

        canonical_def, referenced = _canonical_definition(query, metric.team, user)
        new_hash = canonical_query_hash(query)
        changed = new_hash != metric.source_insight_query_hash

        metric.definition = canonical_def
        metric.referenced_table_names = referenced
        metric.source_insight_query_hash = new_hash
        changed_fields = {"definition", "referenced_table_names", "source_insight_query_hash"}
        if changed and metric.status == MetricStatus.APPROVED:
            _reset_to_proposed(metric)
            changed_fields |= _APPROVAL_FIELDS

        metric.save(update_fields=[*changed_fields, "updated_at"])
    capture_metric_event(METRIC_UPDATED_EVENT, metric, team=metric.team, user=user, request=request)
    return metric


def _apply_soft_delete(metric: Metric) -> None:
    metric.deleted = True
    metric.deleted_at = timezone.now()
    metric.save(update_fields=["deleted", "deleted_at", "updated_at"])


def soft_delete_metric(metric: Metric, user: Optional[User] = None, request: "Request | None" = None) -> None:
    with team_scope(metric.team_id):
        _apply_soft_delete(metric)
    capture_metric_event(METRIC_DELETED_EVENT, metric, team=metric.team, user=user, request=request)


def _batch_team(metrics: list[Metric]) -> Team:
    """The single team a bulk batch belongs to, loaded once so event capture doesn't refetch per metric."""
    team_ids = {metric.team_id for metric in metrics}
    if len(team_ids) > 1:
        raise ValueError("A bulk metric operation must stay within one team.")
    return Team.objects.get(pk=team_ids.pop())


def _lock_batch(team_id: int, metrics: list[Metric]) -> dict[UUID, Metric]:
    """Re-read and row-lock the batch, keyed by id.

    Locks in ``pk`` order so two concurrent bulk operations over overlapping rows queue behind each
    other instead of deadlocking. A metric missing from the result was deleted between resolution and
    the lock.
    """
    locked = (
        Metric.objects.for_team(team_id)
        .filter(pk__in=[metric.pk for metric in metrics], deleted=False)
        # Cache owner and created_by so serializing the approve response reads them off the row
        # instead of one posthog_user lookup per metric. Both FKs are nullable, so select_related
        # is a LEFT OUTER JOIN; Postgres rejects FOR UPDATE on the nullable side of an outer join,
        # so scope the lock to the Metric row with of=("self",) (which also keeps the lock off
        # posthog_user).
        .select_for_update(of=("self",))
        .select_related("owner", "created_by")
        .order_by("pk")
    )
    return {metric.id: metric for metric in locked}


def _locked_match(locked: dict[UUID, Metric], requested: Metric) -> Optional[Metric]:
    """The locked row that still holds the name the caller asked for, or None.

    Callers address a metric by name, and a name is freed for reuse. A row renamed between name
    resolution and the lock is no longer the metric that was requested, so the batch leaves it alone
    rather than acting on it under a name nobody sent.
    """
    metric = locked.get(requested.id)
    if metric is None or metric.name != requested.name:
        return None
    return metric


def _capture_after_commit(
    event: str, metrics: list[Metric], *, team: Team, user: Optional[User], request: "Request | None"
) -> None:
    for metric in metrics:
        transaction.on_commit(partial(capture_metric_event, event, metric, team=team, user=user, request=request))


def bulk_approve_metrics(
    metrics: list[Metric], user: Optional[User], request: "Request | None" = None
) -> tuple[list[Metric], list[MetricBulkSkip]]:
    """Approve every approvable metric in one transaction, reporting the rest as skipped with a reason.

    Drift is checked against the locked rows, so a metric that drifted or was approved between the
    caller rendering it and this call is skipped rather than approved. Response order follows the
    request.
    """
    if not metrics:
        return [], []
    team = _batch_team(metrics)
    approved: list[Metric] = []
    skipped: list[MetricBulkSkip] = []

    with team_scope(team.id), transaction.atomic():
        locked = _lock_batch(team.id, metrics)
        drifted = compute_drift(locked.values())
        for requested in metrics:
            metric = _locked_match(locked, requested)
            if metric is None:
                skipped.append(MetricBulkSkip(name=requested.name, reason=BULK_SKIP_NOT_FOUND))
            elif drifted[metric.id]:
                skipped.append(MetricBulkSkip(name=metric.name, reason=BULK_SKIP_DRIFTED))
            elif metric.status == MetricStatus.APPROVED:
                skipped.append(MetricBulkSkip(name=metric.name, reason=BULK_SKIP_ALREADY_APPROVED))
            else:
                # Per-instance save, never a queryset UPDATE: the audit trail only fires in save().
                _apply_approval(metric, user)
                approved.append(metric)
        _capture_after_commit(METRIC_APPROVED_EVENT, approved, team=team, user=user, request=request)

    return approved, skipped


def bulk_soft_delete_metrics(
    metrics: list[Metric], user: Optional[User] = None, request: "Request | None" = None
) -> tuple[list[Metric], list[MetricBulkSkip]]:
    """Soft-delete a batch in one transaction, freeing their names for reuse."""
    if not metrics:
        return [], []
    team = _batch_team(metrics)
    deleted: list[Metric] = []
    skipped: list[MetricBulkSkip] = []

    with team_scope(team.id), transaction.atomic():
        # Same pk lock order as bulk_approve_metrics, so a mixed approve/delete pair can't deadlock.
        locked = _lock_batch(team.id, metrics)
        for requested in metrics:
            metric = _locked_match(locked, requested)
            if metric is None:
                skipped.append(MetricBulkSkip(name=requested.name, reason=BULK_SKIP_NOT_FOUND))
                continue
            _apply_soft_delete(metric)
            deleted.append(metric)
        _capture_after_commit(METRIC_DELETED_EVENT, deleted, team=team, user=user, request=request)

    return deleted, skipped


def _reset_to_proposed(metric: Metric) -> None:
    metric.status = MetricStatus.PROPOSED
    metric.approved_by = None
    metric.approved_at = None


def metrics_for_team(team: Team) -> QuerySet[Metric]:
    """Live (non-deleted) metrics for a team, newest first."""
    return Metric.objects.for_team(team.id).filter(deleted=False).order_by("-created_at")


def approved_metric_names_for_team(team: Team, user: Optional[User]) -> list[str]:
    """Names of the team's approved, non-drifted metrics, sorted, as the given caller may see them.

    Team scoping alone would be broader than the `system.information_schema.metrics` read this
    listing stands in for: that loader fails closed unless the caller holds `data_catalog` viewer
    access, so a caller denied the resource must not receive the names here either. A ``user`` of
    None is a trusted system/agent caller, as in ``_require_insight_viewer_access``.

    Definitions are deliberately not part of the result, so the per-metric denied-table filtering the
    information_schema loader applies has nothing to hide here.
    """
    if user is not None and not UserAccessControl(user=user, team=team).check_access_level_for_resource(
        "data_catalog", "viewer"
    ):
        return []
    approved = list(metrics_for_team(team).filter(status=MetricStatus.APPROVED).order_by("name"))
    drifted = compute_drift(approved)
    return [metric.name for metric in approved if not drifted[metric.id]]
