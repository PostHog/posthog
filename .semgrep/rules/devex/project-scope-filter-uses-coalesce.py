# Test cases for project-scope-filter-uses-coalesce.
# ruff: noqa
from django.db import models
from django.db.models import Q

from posthog.models import Team
from products.event_definitions.backend.models import EventDefinition, effective_project_id_expr


def or_form(project_id):
    return EventDefinition.objects.filter(
        # ruleid: project-scope-filter-uses-coalesce
        Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id),
        name__in=["a"],
    )


def or_form_reversed(project_id):
    return EventDefinition.objects.filter(
        # ruleid: project-scope-filter-uses-coalesce
        Q(project_id__isnull=True, team_id=project_id) | Q(project_id=project_id)
    )


def or_form_qualified(project_id):
    return EventDefinition.objects.filter(
        # ruleid: project-scope-filter-uses-coalesce
        models.Q(project_id=project_id) | models.Q(project_id__isnull=True, team_id=project_id)
    )


def or_form_behind_a_chained_call(project_id):
    return EventDefinition.objects.select_related("team").filter(
        # ruleid: project-scope-filter-uses-coalesce
        Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id)
    )


def coalesce_form(project_id):
    # ok: project-scope-filter-uses-coalesce
    return EventDefinition.objects.alias(effective_project_id=effective_project_id_expr()).filter(
        effective_project_id=project_id, name__in=["a"]
    )


def unrelated_or(project_id, team_id):
    return EventDefinition.objects.filter(
        # ok: project-scope-filter-uses-coalesce
        Q(project_id=project_id) | Q(team_id=team_id)
    )


def two_different_scope_values(project_id, team_id):
    # Not equivalent to a COALESCE: the legacy branch scopes to a different value, so rewriting
    # would change which rows come back.
    return EventDefinition.objects.filter(
        # ok: project-scope-filter-uses-coalesce
        Q(project_id=project_id) | Q(project_id__isnull=True, team_id=team_id)
    )


def model_without_the_coalesce_index(project_id):
    # `Team` has no `COALESCE(project_id, team_id)` index, so the rewrite buys nothing.
    return Team.objects.filter(
        # ok: project-scope-filter-uses-coalesce
        Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id)
    )
