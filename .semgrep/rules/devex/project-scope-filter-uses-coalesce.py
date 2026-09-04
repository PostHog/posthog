# Test cases for project-scope-filter-uses-coalesce.
# Findings anchor on the line the matched `filter()` expression starts on, so each annotation sits
# above the statement rather than above the `Q(...) | Q(...)` inside it.
# ruff: noqa
from django.db import models
from django.db.models import Q

from posthog.models import Team
from ee.models.event_definition import EnterpriseEventDefinition
from products.event_definitions.backend.models import EventDefinition, effective_project_id_expr


def or_form(project_id):
    # ruleid: project-scope-filter-uses-coalesce
    return EventDefinition.objects.filter(
        Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id),
        name__in=["a"],
    )


def or_form_reversed(project_id):
    # ruleid: project-scope-filter-uses-coalesce
    return EventDefinition.objects.filter(Q(project_id__isnull=True, team_id=project_id) | Q(project_id=project_id))


def or_form_qualified(project_id):
    # ruleid: project-scope-filter-uses-coalesce
    return EventDefinition.objects.filter(
        models.Q(project_id=project_id) | models.Q(project_id__isnull=True, team_id=project_id)
    )


def or_form_on_the_enterprise_subclass(project_id):
    # ruleid: project-scope-filter-uses-coalesce
    return EnterpriseEventDefinition.objects.filter(
        Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id)
    )


def or_form_behind_one_chained_call(project_id):
    # ruleid: project-scope-filter-uses-coalesce
    return EventDefinition.objects.select_related("team").filter(
        Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id)
    )


def or_form_behind_a_long_chain(project_id):
    # ruleid: project-scope-filter-uses-coalesce
    return (
        EventDefinition.objects.select_related("team")
        .order_by("name")
        .distinct()
        .filter(Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id))
    )


def coalesce_form(project_id):
    # ok: project-scope-filter-uses-coalesce
    return EventDefinition.objects.alias(effective_project_id=effective_project_id_expr()).filter(
        effective_project_id=project_id, name__in=["a"]
    )


def unrelated_or(project_id, team_id):
    # ok: project-scope-filter-uses-coalesce
    return EventDefinition.objects.filter(Q(project_id=project_id) | Q(team_id=team_id))


def two_different_scope_values(project_id, team_id):
    # Not equivalent to a COALESCE: the legacy branch scopes to a different value, so rewriting
    # would change which rows come back.
    # ok: project-scope-filter-uses-coalesce
    return EventDefinition.objects.filter(Q(project_id=project_id) | Q(project_id__isnull=True, team_id=team_id))


def model_without_the_coalesce_index(project_id):
    # `Team` has no `COALESCE(project_id, team_id)` index, so the rewrite buys nothing.
    # ok: project-scope-filter-uses-coalesce
    return Team.objects.filter(Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id))


def excluded_rather_than_filtered(project_id):
    # The suggested rewrite is a `filter()`. Applied to an exclude it inverts the result set.
    # ok: project-scope-filter-uses-coalesce
    return EventDefinition.objects.exclude(Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id))


def negated_inside_filter(project_id):
    # Same inversion, spelled with `~` instead of `exclude()`.
    # ok: project-scope-filter-uses-coalesce
    return EventDefinition.objects.filter(~(Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id)))
