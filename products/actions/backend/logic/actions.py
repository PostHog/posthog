"""Queries and writes over the action model. The facade maps what these return to contracts."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.db.models import F, Q, QuerySet
from django.db.models.functions import Substr

from posthog.helpers.full_text_search import build_rank

from products.actions.backend.facade.contracts import ActionCatalogEntry
from products.actions.backend.models.action import Action

if TYPE_CHECKING:
    from posthog.models import Team, User

    from products.access_control.backend.facade.user_access_control import UserAccessControl

SEARCH_FIELDS: dict[str, Any] = {"name": "A", "description": "C"}
SEARCH_RANK_THRESHOLD = 0.05
CATALOG_DESCRIPTION_LENGTH = 200


def scoped(*, project_id: int | None, team_id: int | None) -> QuerySet[Action]:
    """Actions in one project, or in one team. A caller must say which, because both are in use and
    they differ for a child environment: actions live on the project's root team."""
    if project_id is not None and team_id is not None:
        raise ValueError("Scope actions by project_id or by team_id, not both")
    if project_id is not None:
        return Action.objects.filter(team__project_id=project_id)
    if team_id is not None:
        return Action.objects.filter(team_id=team_id)
    raise ValueError("Scope actions by project_id or by team_id")


def live_or_all(queryset: QuerySet[Action], *, include_deleted: bool) -> QuerySet[Action]:
    return queryset if include_deleted else queryset.filter(deleted=False)


def top_actions(*, project_id: int, limit: int) -> QuerySet[Action]:
    """Pinned actions first, then the most recently calculated: the order web analytics reads goals in."""
    return Action.objects.filter(team__project_id=project_id, deleted=False).order_by(
        "pinned_at", "-last_calculated_at"
    )[:limit]


def team_id_of(*, action_id: int, include_deleted: bool) -> int | None:
    # nosemgrep: idor-lookup-without-team (callers hold an id from a trusted source and need the owning team)
    queryset = Action.objects.filter(id=action_id)
    if not include_deleted:
        queryset = queryset.filter(deleted=False)
    return queryset.values_list("team_id", flat=True).first()


def readable_ids(
    *,
    project_id: int,
    action_ids: Collection[int],
    access_control: UserAccessControl,
    required_level: Any,
) -> set[int]:
    return {
        action.id
        for action in Action.objects.filter(pk__in=action_ids, team__project_id=project_id)
        if access_control.check_access_level_for_object(action, required_level)
    }


def accessible_ids(*, team_id: int, action_ids: Collection[int], access_control: UserAccessControl) -> set[int]:
    return set(
        access_control.filter_queryset_by_access_level(
            Action.objects.filter(team_id=team_id, pk__in=action_ids, deleted=False), resource="action"
        ).values_list("pk", flat=True)
    )


def catalog_entries(
    *, team_id: int, access_control: UserAccessControl, limit: int, using: str | None
) -> list[ActionCatalogEntry]:
    manager = Action.objects.using(using) if using else Action.objects
    rows = (
        access_control.filter_queryset_by_access_level(
            manager.filter(team_id=team_id, deleted=False), resource="action"
        )
        .annotate(short_description=Substr("description", 1, CATALOG_DESCRIPTION_LENGTH))
        .order_by("-updated_at", "-pk")
        .values_list("pk", "name", "short_description")[:limit]
    )
    return [
        ActionCatalogEntry(id=pk, name=name, short_description=short_description)
        for pk, name, short_description in rows
    ]


def search(
    *,
    project_id: int,
    query: str | None,
    access_control: UserAccessControl,
    limit: int,
    offset: int,
    include_deleted: bool,
    include_count: bool,
) -> tuple[list[dict[str, Any]], int]:
    queryset = access_control.filter_queryset_by_access_level(Action.objects.filter(team__project_id=project_id))
    if not include_deleted:
        queryset = queryset.filter(deleted=False)
    if query:
        queryset = queryset.annotate(rank=build_rank(SEARCH_FIELDS, query, config="simple"))
        queryset = queryset.filter(rank__gt=SEARCH_RANK_THRESHOLD).order_by("-rank")
    else:
        queryset = queryset.order_by(F("name").asc(nulls_first=True))
    total_count = queryset.count() if include_count else 0
    fields = ["id", "name", "description", "created_by_id"]
    if query:
        fields.append("rank")
    return list(queryset[offset : offset + limit].values(*fields)), total_count


def create(
    *,
    team: Team,
    name: str | None,
    steps_json: Sequence[Mapping[str, object]] | None,
    description: str,
    created_by: User | None,
    pinned_at: datetime | None,
) -> Action:
    return Action.objects.create(
        team=team,
        name=name,
        steps_json=[dict(step) for step in steps_json] if steps_json is not None else None,
        description=description,
        created_by=created_by,
        pinned_at=pinned_at,
    )


def to_summarize(start_dt: datetime) -> QuerySet[Action]:
    """Actions whose AI summary is missing or older than their last edit, in a fixed order.

    Temporal replays an activity with the same offsets, so the order must not move between attempts:
    the `last_summarized_at=start_dt` branch keeps rows this run already summarized in the set.
    """
    filter_conditions = Q(
        # Only orgs that have accepted data processing
        team__organization__is_ai_data_processing_approved=True,
        # Only actions updated before the start date
        updated_at__lte=start_dt,
    ) & (
        # Never summarized actions but not deleted
        Q(last_summarized_at__isnull=True, deleted=False)
        # Actions updated after last summarization workflow
        | Q(updated_at__gte=F("last_summarized_at"))
        | Q(last_summarized_at=start_dt)
    )
    return Action.objects.filter(filter_conditions).order_by("id", "team_id", "updated_at")


def to_embed(*, start_dt: datetime, embedding_version: int | None) -> QuerySet[Action]:
    query = (
        # Include only updated actions.
        Q(last_summarized_at__gt=F("embedding_last_synced_at"))
        # Or actions that haven't never been synced but have summaries.
        | (Q(embedding_last_synced_at__isnull=True) & Q(last_summarized_at__isnull=False))
    )

    # Temporal workflows must be deterministic, so a run started without a version does not look at versions.
    if embedding_version is not None:
        query |= (
            # Or actions that don't have an embedding version.
            Q(embedding_version__isnull=True)
            # Or actions with an old embedding version.
            | Q(embedding_version__lt=embedding_version)
        )

    return Action.objects.filter(
        Q(
            # Include only actions that have been summarized.
            last_summarized_at__lte=start_dt,
            # And they must have a summary to prevent infinite loops.
            summary__isnull=False,
        )
        & query
    ).order_by("updated_at", "id")
