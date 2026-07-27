"""Metric write path and approval lifecycle.

Names are reserved forever per team: creating with an existing name refines that metric, and creating
with a soft-deleted name resurrects the row as ``proposed``. A metric can be created from an insight
(its query is snapshotted server-side and drift is flagged for re-review). Promotion to ``approved``
is blocked while a metric is drifted. All transitions emit capture events for success-criteria
measurement.
"""

import re
from typing import Optional

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.models.scoping import team_scope
from posthog.rbac.user_access_control import UserAccessControl

from products.product_analytics.backend.models.insight import Insight

from ..facade.enums import CreatedSource, MetricStatus
from ..models import METRIC_NAME_REGEX, Metric
from .drift import canonical_query_hash, compute_drift, effective_insight_query, fetch_insight
from .exceptions import MetricDrifted, SourceInsightUnavailable
from .validation import validate_metric_definition


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
_APPROVAL_RELEVANT_FIELDS = frozenset({"description", "unit"})


def _capture(user: Optional[User], team: Team, event: str, metric: Metric) -> None:
    if user is None:
        return
    report_user_action(
        user=user,
        event=event,
        team=team,
        properties={
            "metric_id": str(metric.id),
            "metric_name": metric.name,
            "definition_kind": metric.definition_kind,
            "status": metric.status,
            "created_source": metric.created_source,
        },
    )


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


def _resurrect_or_refine(metric: Metric, fields: dict) -> None:
    if metric.deleted:
        metric.deleted = False
        metric.deleted_at = None
        _reset_to_proposed(metric)
    elif _invalidates_approval(metric, fields):
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
) -> Metric:
    """Create a metric, or refine/resurrect the one already holding ``name`` for this team.

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
                existing = Metric.objects.for_team(team.id).filter(name=name).select_for_update().first()
                created = existing is None
                if existing is not None:
                    _resurrect_or_refine(existing, fields)
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
                existing = Metric.objects.for_team(team.id).filter(name=name).select_for_update().first()
                if existing is None:
                    raise
                _resurrect_or_refine(existing, fields)
                metric, created = existing, False

    _capture(user, team, "data catalog metric created" if created else "data catalog metric updated", metric)
    return metric


def update_metric(metric: Metric, *, team: Team, user: Optional[User], **fields) -> Metric:
    """Partially update a metric. Name is write-once; editing an approved definition resets approval."""
    if "name" in fields:
        raise ValidationError({"name": "Metric name is write-once and cannot be changed."})

    # Route definition / insight-link through the same resolver as create, so a PATCH honors the
    # definition-XOR-insight rule, snapshots (and validates) on relink, and drops the hash on unlink.
    definition_arg = fields.pop("definition", _UNSET)
    source_insight_arg = fields.pop("source_insight_short_id", _UNSET)
    fields.update(_resolve_definition_fields(definition_arg, source_insight_arg, team, user))

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
    _capture(user, team, "data catalog metric updated", metric)
    return metric


def approve_metric(metric: Metric, user: Optional[User]) -> Metric:
    """Bless a metric as canonical. Blocked (409) while drifted. Idempotent on an already-approved metric."""
    with team_scope(metric.team_id), transaction.atomic():
        metric = Metric.objects.for_team(metric.team_id).select_for_update().get(pk=metric.pk)
        if compute_drift([metric])[metric.id]:
            raise MetricDrifted()
        if metric.status == MetricStatus.APPROVED:
            return metric
        metric.status = MetricStatus.APPROVED
        metric.approved_by = user
        metric.approved_at = timezone.now()
        metric.save(update_fields=[*_APPROVAL_FIELDS, "updated_at"])
    _capture(user, metric.team, "data catalog metric approved", metric)
    return metric


def refresh_metric_from_insight(metric: Metric, user: Optional[User]) -> Metric:
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
    _capture(user, metric.team, "data catalog metric updated", metric)
    return metric


def soft_delete_metric(metric: Metric, user: Optional[User] = None) -> None:
    metric.deleted = True
    metric.deleted_at = timezone.now()
    with team_scope(metric.team_id):
        metric.save(update_fields=["deleted", "deleted_at", "updated_at"])
    _capture(user, metric.team, "data catalog metric deleted", metric)


def _reset_to_proposed(metric: Metric) -> None:
    metric.status = MetricStatus.PROPOSED
    metric.approved_by = None
    metric.approved_at = None


def metrics_for_team(team: Team) -> QuerySet[Metric]:
    """Live (non-deleted) metrics for a team, newest first."""
    return Metric.objects.for_team(team.id).filter(deleted=False).order_by("-created_at")
