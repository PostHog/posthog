"""Metric write path — upsert with reserved-name semantics, partial update, soft delete.

Names are reserved forever per team: creating with an existing name refines that metric, and
creating with a soft-deleted name resurrects the row as ``proposed`` rather than minting a new
identity. Concurrent same-name creates collapse to one row via the unique constraint + retry.
"""

import re
from typing import Optional

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.models import Team, User
from posthog.models.scoping import team_scope

from ..facade.enums import CreatedSource, MetricStatus
from ..models import METRIC_NAME_REGEX, Metric
from .validation import validate_metric_definition


class _Unset:
    """Sentinel for upsert fields the caller did not supply: kept as-is on refine, defaulted on create.

    A plain ``None`` default cannot express this because ``None`` is a legitimate value for
    ``definition``/``confidence``/``owner`` (an explicit clear), distinct from "not provided".
    """


_UNSET = _Unset()


def _canonical_definition(
    definition: Optional[dict], team: Team, user: Optional[User]
) -> tuple[Optional[dict], list[str]]:
    if definition is None:
        return None, []
    return validate_metric_definition(definition, team, user)


def _resurrect_or_refine(metric: Metric, fields: dict) -> None:
    if metric.deleted:
        metric.deleted = False
        metric.deleted_at = None
        metric.status = MetricStatus.PROPOSED
        metric.approved_by = None
        metric.approved_at = None
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
    created_source: CreatedSource | _Unset = _UNSET,
    ai_model: str | _Unset = _UNSET,
    confidence: float | None | _Unset = _UNSET,
    reasoning: str | _Unset = _UNSET,
) -> Metric:
    """Create a metric, or refine/resurrect the one already holding ``name`` for this team.

    Refine is a partial merge: only the fields the caller supplies are written, so a refine that
    omits a field leaves that field (a stored ``definition``, provenance, ...) untouched rather than
    resetting it. On create, omitted fields fall back to the model defaults (``owner`` to ``user``).
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

    if not isinstance(definition, _Unset):
        canonical_def, referenced = _canonical_definition(definition, team, user)
        fields["definition"] = canonical_def
        fields["referenced_table_names"] = referenced

    # team_scope so the ModelActivityMixin's before-update lookup (via the fail-closed manager)
    # works regardless of caller context (viewset, Celery, MCP, tests).
    with team_scope(team.id):
        try:
            with transaction.atomic():
                existing = Metric.objects.for_team(team.id).filter(name=name).select_for_update().first()
                if existing is not None:
                    _resurrect_or_refine(existing, fields)
                    return existing
                return Metric.objects.for_team(team.id).create(
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
                return existing


def update_metric(metric: Metric, *, team: Team, user: Optional[User], **fields) -> Metric:
    """Partially update a metric. Name is write-once. Definition changes are re-validated."""
    if "name" in fields:
        raise ValidationError({"name": "Metric name is write-once and cannot be changed."})

    if "definition" in fields:
        canonical_def, referenced = _canonical_definition(fields["definition"], team, user)
        fields["definition"] = canonical_def
        fields["referenced_table_names"] = referenced

    for key, value in fields.items():
        setattr(metric, key, value)
    with team_scope(team.id):
        metric.save()
    return metric


def soft_delete_metric(metric: Metric) -> None:
    metric.deleted = True
    metric.deleted_at = timezone.now()
    with team_scope(metric.team_id):
        metric.save()


def metrics_for_team(team: Team) -> QuerySet[Metric]:
    """Live (non-deleted) metrics for a team, newest first."""
    return Metric.objects.for_team(team.id).filter(deleted=False).order_by("-created_at")
