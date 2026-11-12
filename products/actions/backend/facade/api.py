"""
Facade API for actions.

This is the module that other apps / the presentation layer should
import from. It accepts plain inputs and returns HogQL conditions or
contract DTOs, never ORM instances or QuerySets.

Do NOT:
- Import DRF / serializers / HTTP concerns here
- Return ORM instances or QuerySets
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.db import router

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.paging import Page

from products.actions.backend.facade import contracts
from products.actions.backend.logic import (
    actions as logic,
    details,
    saved_handlers,
)
from products.actions.backend.models.action import Action as ActionModel

if TYPE_CHECKING:
    from posthog.hogql import ast

    from posthog.models import Team, User

    from products.access_control.backend.facade.user_access_control import UserAccessControl

logger = structlog.get_logger(__name__)

__all__ = [
    "acount_actions_to_summarize",
    "action_filter_conditions",
    "action_read_db_alias",
    "add_action",
    "aget_action",
    "alist_actions",
    "alist_actions_to_embed",
    "alist_actions_to_summarize",
    "amark_actions_embedded",
    "asave_action_summaries",
    "accessible_action_ids",
    "change_action_tags",
    "count_action_references",
    "count_live_actions",
    "create_action",
    "edit_action",
    "existing_action_ids",
    "find_action_id_by_name",
    "find_action_references",
    "find_actions_by_name",
    "find_action_team_id",
    "get_action",
    "get_action_detail",
    "get_action_details",
    "get_action_inventory",
    "get_action_names",
    "get_actions",
    "list_action_catalog",
    "list_action_details",
    "list_actions",
    "list_actions_in_list_order",
    "list_top_actions",
    "on_action_saved",
    "readable_action_ids",
    "search_actions",
]


def _to_creator(user: User | None) -> contracts.ActionCreator | None:
    if user is None:
        return None
    return contracts.ActionCreator(
        id=user.id,
        uuid=user.uuid,
        distinct_id=user.distinct_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=user.hedgehog_config,
        role_at_organization=user.role_at_organization,
    )


def _to_detail(action: ActionModel) -> contracts.ActionDetail:
    tagged_items = getattr(action, "prefetched_tags", None)
    tags = (
        tuple(tagged_item.tag.name for tagged_item in tagged_items)
        if tagged_items is not None
        else tuple(action.tagged_items.values_list("tag__name", flat=True))
    )
    return contracts.ActionDetail(
        id=action.id,
        team_id=action.team_id,
        name=action.name,
        description=action.description,
        tags=tags,
        post_to_slack=action.post_to_slack,
        slack_message_format=action.slack_message_format,
        steps=tuple(action.steps),
        created_at=action.created_at,
        created_by_id=action.created_by_id,
        created_by=_to_creator(action.created_by),
        deleted=action.deleted,
        last_calculated_at=action.last_calculated_at,
        bytecode_error=action.bytecode_error,
        pinned_at=action.pinned_at,
    )


def _to_write_result(action: ActionModel) -> contracts.ActionWriteResult:
    return contracts.ActionWriteResult(
        action=_to_detail(action), analytics=contracts.ActionAnalytics(**action.get_analytics_metadata())
    )


def _to_contract(action: ActionModel) -> contracts.Action:
    return contracts.Action(
        id=action.id,
        team_id=action.team_id,
        name=action.name,
        description=action.description,
        steps=tuple(action.steps),
        deleted=action.deleted,
        created_by_id=action.created_by_id,
        created_at=action.created_at,
        updated_at=action.updated_at,
        pinned_at=action.pinned_at,
        last_calculated_at=action.last_calculated_at,
        summary=action.summary,
    )


# Reads


def get_action(
    *,
    action_id: int,
    project_id: int | None = None,
    team_id: int | None = None,
    include_deleted: bool = True,
) -> contracts.Action:
    """One action, scoped to a project or to a team. Raises `ActionNotFound` outside that scope.

    Actions live on the project's root team, so a child environment finds them by `project_id`.
    `team_id` matches the owning team exactly. A deleted action is returned unless `include_deleted=False`,
    because a saved query keeps naming an action after it is deleted.
    """
    queryset = logic.live_or_all(logic.scoped(project_id=project_id, team_id=team_id), include_deleted=include_deleted)
    try:
        return _to_contract(queryset.get(pk=action_id))
    except ActionModel.DoesNotExist:
        raise contracts.ActionNotFound(f"Action {action_id} does not exist") from None


async def aget_action(
    *,
    action_id: int,
    project_id: int | None = None,
    team_id: int | None = None,
    include_deleted: bool = True,
) -> contracts.Action:
    queryset = logic.live_or_all(logic.scoped(project_id=project_id, team_id=team_id), include_deleted=include_deleted)
    try:
        return _to_contract(await queryset.aget(pk=action_id))
    except ActionModel.DoesNotExist:
        raise contracts.ActionNotFound(f"Action {action_id} does not exist") from None


def get_actions(
    *,
    action_ids: Iterable[int],
    project_id: int | None = None,
    team_id: int | None = None,
    include_deleted: bool = True,
) -> list[contracts.Action]:
    """The actions among `action_ids` that exist in the scope. A missing id is left out, not an error."""
    queryset = logic.live_or_all(logic.scoped(project_id=project_id, team_id=team_id), include_deleted=include_deleted)
    return [_to_contract(action) for action in queryset.filter(pk__in=list(action_ids))]


def list_actions(
    *, project_id: int | None = None, team_id: int | None = None, include_deleted: bool = False
) -> list[contracts.Action]:
    """Every action in the scope, live ones only unless `include_deleted`."""
    queryset = logic.live_or_all(logic.scoped(project_id=project_id, team_id=team_id), include_deleted=include_deleted)
    return [_to_contract(action) for action in queryset]


async def alist_actions(
    *, project_id: int | None = None, team_id: int | None = None, include_deleted: bool = False
) -> list[contracts.Action]:
    queryset = logic.live_or_all(logic.scoped(project_id=project_id, team_id=team_id), include_deleted=include_deleted)
    return [_to_contract(action) async for action in queryset]


def list_top_actions(*, project_id: int, limit: int) -> list[contracts.Action]:
    """Up to `limit` live actions, pinned ones first and then the most recently calculated."""
    return [_to_contract(action) for action in logic.top_actions(project_id=project_id, limit=limit)]


def get_action_names(*, project_id: int, action_ids: Iterable[int]) -> dict[int, str | None]:
    """Name by id for the actions among `action_ids` in the project, deleted ones included."""
    return dict(
        logic.scoped(project_id=project_id, team_id=None).filter(pk__in=list(action_ids)).values_list("pk", "name")
    )


def existing_action_ids(*, project_id: int, action_ids: Iterable[int]) -> list[int]:
    """The ids among `action_ids` that name an action in the project, deleted ones included."""
    return list(
        logic.scoped(project_id=project_id, team_id=None).filter(pk__in=list(action_ids)).values_list("pk", flat=True)
    )


def find_action_team_id(*, action_id: int, include_deleted: bool = True) -> int | None:
    """The team that owns an action, or None when it does not exist.

    Unscoped: only for a caller that got the id from a trusted source, such as a save signal, or
    that checks the user's access to the returned team itself.
    """
    return logic.team_id_of(action_id=action_id, include_deleted=include_deleted)


def find_actions_by_name(
    *, name: str, project_id: int | None = None, team_id: int | None = None, include_deleted: bool = False
) -> list[contracts.Action]:
    """The actions in the scope with exactly this name, oldest first. Names are not unique."""
    queryset = logic.live_or_all(
        logic.scoped(project_id=project_id, team_id=team_id), include_deleted=include_deleted
    ).filter(name=name)
    return [_to_contract(action) for action in queryset.order_by("pk")]


def get_action_inventory(*, team_id: int, recent_limit: int) -> contracts.ActionInventory:
    """How many live actions the team has, and the `recent_limit` it changed most recently."""
    queryset = logic.scoped(project_id=None, team_id=team_id).filter(deleted=False)
    total = queryset.count()
    recent = queryset.order_by("-updated_at")[:recent_limit].values("id", "name", "updated_at")
    return contracts.ActionInventory(
        total_count=total,
        recent=tuple(
            contracts.ActionRecentEntry(id=row["id"], name=row["name"], updated_at=row["updated_at"]) for row in recent
        ),
    )


# Reads that apply a user's access


def readable_action_ids(
    *,
    project_id: int,
    action_ids: Collection[int],
    access_control: UserAccessControl,
    required_level: Any = "viewer",
) -> set[int]:
    """The ids among `action_ids` that name an action in the project the user holds `required_level` on.

    Each action is checked as an object, so an action from a sibling environment resolves against the
    rules of the team `access_control` is for.
    """
    return logic.readable_ids(
        project_id=project_id, action_ids=action_ids, access_control=access_control, required_level=required_level
    )


def accessible_action_ids(*, team_id: int, action_ids: Collection[int], access_control: UserAccessControl) -> set[int]:
    """The ids among `action_ids` that name a live action of the team the user may list."""
    return logic.accessible_ids(team_id=team_id, action_ids=action_ids, access_control=access_control)


def action_read_db_alias() -> str:
    """The database alias a catalog read of actions runs on, so a caller can bound that connection."""
    return router.db_for_read(ActionModel)


def list_action_catalog(
    *, team_id: int, access_control: UserAccessControl, limit: int, using: str | None = None
) -> list[contracts.ActionCatalogEntry]:
    """The team's live actions the user may list, most recently updated first."""
    return logic.catalog_entries(team_id=team_id, access_control=access_control, limit=limit, using=using)


def search_actions(
    *,
    project_id: int,
    query: str | None,
    access_control: UserAccessControl,
    limit: int,
    offset: int = 0,
    include_deleted: bool = True,
    with_access_levels: bool = False,
    include_count: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Ranked full-text search over a project's actions, in the result shape of core search.

    Without a query the actions come in name order. ``with_access_levels`` adds ``user_access_level``,
    the user's resolved level for each action. ``include_count=False`` skips the count query and
    reports a total of 0.
    """
    rows, total_count = logic.search(
        project_id=project_id,
        query=query,
        access_control=access_control,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
        include_count=include_count,
    )
    access_levels = (
        access_control.bulk_object_access_levels("action", [(str(row["id"]), row["created_by_id"]) for row in rows])
        if with_access_levels
        else {}
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        result: dict[str, Any] = {
            "type": "action",
            "result_id": str(row["id"]),
            "extra_fields": {"name": row["name"], "description": row["description"]},
        }
        if query:
            result["rank"] = row["rank"]
        if with_access_levels:
            result["user_access_level"] = access_levels.get(str(row["id"]))
        results.append(result)
    return results, total_count


def list_action_details(
    *,
    team_id: int,
    filters: contracts.ActionListFilters,
    access: contracts.ActionListAccess | None,
    offset: int = 0,
    limit: int | None = None,
) -> Page[contracts.ActionDetail]:
    """The team's live actions that pass the filters, from `offset` on, at most `limit` of them.

    `access` narrows the list and its count to what the viewer's access control rules allow. Without a
    limit the list holds every action from `offset` on, and its count is `offset` plus the actions
    returned, which saves a count query on the path the taxonomic filter shares.
    """
    page = details.list_details(team_id=team_id, filters=filters, access=access, offset=offset, limit=limit)
    return page.map(_to_detail)


def get_action_detail(*, team_id: int, action_id: int) -> contracts.ActionDetail:
    """One action of the team, deleted or not. Raises `ActionNotFound` when the team has none with that id."""
    return _to_detail(details.get_detail(team_id=team_id, action_id=action_id))


def get_action_details(*, team_id: int, action_ids: Sequence[int]) -> list[contracts.ActionDetail]:
    """The team's actions among `action_ids`, deleted ones included, in the order of `action_ids`.

    A missing id is left out, not an error.
    """
    by_id = {
        action.id: _to_detail(action)
        for action in details.with_relations(logic.scoped(project_id=None, team_id=team_id)).filter(
            pk__in=list(action_ids)
        )
    }
    return [by_id[action_id] for action_id in action_ids if action_id in by_id]


def count_live_actions(*, team_id: int) -> int:
    return details.count_live(team_id=team_id)


def find_action_id_by_name(*, team_id: int, name: str, exclude_action_id: int | None = None) -> int | None:
    """The id of a live action of the team with exactly this name, other than `exclude_action_id`."""
    return details.colliding_action_id(team_id=team_id, name=name, exclude_action_id=exclude_action_id)


def add_action(*, team_id: int, created_by: User | None, write: contracts.ActionWrite) -> contracts.ActionWriteResult:
    """Create an action in the team with the fields the write names. Saving compiles its bytecode.

    A child environment's team is swapped for its project's root team, where actions live. Tags the write
    names are set after the action is saved.
    """
    return _to_write_result(details.create(team_id=team_id, created_by=created_by, write=write))


def edit_action(*, team_id: int, action_id: int, write: contracts.ActionWrite) -> contracts.ActionWriteResult:
    """Change the fields the write names on one action of the team, deleted or not.

    Raises `ActionNotFound` when the team has no action with that id. Tags the write names are replaced
    after the action is saved.
    """
    action = details.get_detail(team_id=team_id, action_id=action_id)
    return _to_write_result(details.update(action=action, write=write))


def find_action_references(*, team_id: int, project_id: int, action_id: int) -> list[contracts.ActionReference]:
    """The insights, experiments, cohorts and hog functions that use the action, 50 at most.

    Deleted resources are left out. Cohorts are read across the project, the other resources in the team.
    """
    # Those products' facades import this one, and every caller of this module would load them.
    from products.actions.backend.logic import references  # noqa: PLC0415

    return references.find(team_id=team_id, project_id=project_id, action_id=action_id)


def count_action_references(*, team_id: int, project_id: int, action_ids: Sequence[int]) -> dict[int, int]:
    """For each action, how many resources `find_action_references` would count, without its cap.

    An action without a reference is absent from the result.
    """
    from products.actions.backend.logic import references  # noqa: PLC0415 — see find_action_references

    return references.count(team_id=team_id, project_id=project_id, action_ids=action_ids)


def list_actions_in_list_order(*, team_id: int, action_ids: Collection[int]) -> list[contracts.Action]:
    """The team's actions among `action_ids`, deleted ones included, in the order of the actions list."""
    queryset = logic.scoped(project_id=None, team_id=team_id).filter(pk__in=list(action_ids))
    return [_to_contract(action) for action in queryset.order_by(*details.DEFAULT_ORDERING)]


def change_action_tags(
    *, team_id: int, action_ids: Sequence[int], tag_action: str, tags: Sequence[str]
) -> list[contracts.ActionTagChange]:
    """Add, remove or set tags on the team's actions among `action_ids`, in the order of `action_ids`.

    `tag_action` is `add`, `remove` or `set`. Tags no other object uses any more are deleted.
    """
    return [
        contracts.ActionTagChange(id=change["id"], tags=tuple(change["tags"]))
        for change in details.change_tags(team_id=team_id, action_ids=action_ids, tag_action=tag_action, tags=tags)
    ]


# HogQL


def action_filter_conditions(*, team: Team, action_ids: Sequence[int]) -> dict[int, ast.Expr]:
    """The HogQL condition matching each action's events, keyed by action id.

    Lets another product filter events by action without holding the Action model, which stays in
    this product. A caller that puts a condition in two places in one query must clone it with
    `clone_expr`, because the HogQL resolver annotates the nodes it walks.

    Scoped to the team's project, the same way actions are read everywhere else.

    An action is absent from the result when it belongs to another project, when it is deleted, or
    when it has no steps. A stepless action compiles to a condition that matches every event, which
    reads as a filter but is not one.
    """
    from posthog.hogql.property import action_to_expr  # noqa: PLC0415 — keeps HogQL off the facade's import path

    if not action_ids:
        return {}

    conditions: dict[int, ast.Expr] = {}
    for action in ActionModel.objects.filter(team__project_id=team.project_id, id__in=action_ids, deleted=False):
        if not action.steps:
            continue
        try:
            conditions[action.id] = action_to_expr(_to_contract(action))
        except Exception:
            # One action with an uncompilable step must not cost the caller the rest of them.
            continue
    return conditions


# Writes


def create_action(
    *,
    team: Team,
    name: str | None,
    steps_json: Sequence[Mapping[str, object]] | None = None,
    description: str = "",
    created_by: User | None = None,
    pinned_at: datetime | None = None,
) -> contracts.Action:
    """Create an action from steps in the stored JSON shape. Saving compiles its bytecode.

    A child environment's team is swapped for its project's root team, where actions live.
    """
    return _to_contract(
        logic.create(
            team=team,
            name=name,
            steps_json=steps_json,
            description=description,
            created_by=created_by,
            pinned_at=pinned_at,
        )
    )


def on_action_saved(handler: Callable[[contracts.ActionSaved], None], *, dispatch_uid: str) -> None:
    """Run `handler` after every save of an action, inside the saving transaction.

    For a product that keeps something derived from actions, such as compiled filters that embed an
    action's matcher. A handler that has slow or external work to do should dispatch a task.
    """
    saved_handlers.register(handler, dispatch_uid=dispatch_uid)


# AI summaries and embeddings


async def alist_actions_to_summarize(
    *, start_dt: datetime, offset: int | None = None, batch_size: int | None = None
) -> list[contracts.Action]:
    """Actions whose AI summary is missing or older than their last edit, in a fixed order.

    Pass both `offset` and `batch_size` for one page, or neither for every action. The order holds
    while a run summarizes, so a retried page reads the same actions.
    """
    queryset = logic.to_summarize(start_dt)
    if offset is not None or batch_size is not None:
        if offset is None or batch_size is None:
            raise ValueError("Cannot provide only offset or only batch_size")
        queryset = queryset[offset : offset + batch_size]
    actions: list[contracts.Action] = []
    async for action in queryset:
        try:
            actions.append(_to_contract(action))
        except Exception as error:
            # One action with an unreadable stored step must not stop the sync for every other team, so it is
            # reported and left out. Its page position is kept, because the next page is read by offset.
            capture_exception(error, additional_properties={"action_id": action.id, "tag": "max_ai"})
            logger.exception("Error reading action to summarize", error=error, action_id=action.id)
    return actions


async def acount_actions_to_summarize(*, start_dt: datetime) -> int:
    return await logic.to_summarize(start_dt).acount()


async def asave_action_summaries(*, summaries: Mapping[int, str], summarized_at: datetime) -> None:
    """Store each action's new summary, stamped with the run that wrote it."""
    if not summaries:
        return
    await ActionModel.objects.abulk_update(
        [
            ActionModel(id=action_id, last_summarized_at=summarized_at, summary=summary)
            for action_id, summary in summaries.items()
        ],
        ["last_summarized_at", "summary"],
    )


async def alist_actions_to_embed(
    *, start_dt: datetime, embedding_version: int | None, offset: int, limit: int
) -> list[contracts.ActionEmbeddingSource]:
    """Summarized actions whose summary has not reached the vector store at `embedding_version`, oldest edit first."""
    rows = logic.to_embed(start_dt=start_dt, embedding_version=embedding_version).values(
        "team_id", "id", "summary", "name", "description", "deleted"
    )[offset : offset + limit]
    return [
        contracts.ActionEmbeddingSource(
            id=row["id"],
            team_id=row["team_id"],
            name=row["name"],
            description=row["description"],
            summary=row["summary"],
            deleted=row["deleted"],
        )
        async for row in rows
    ]


async def amark_actions_embedded(
    *, action_ids: Iterable[int], synced_at: datetime, embedding_version: int | None
) -> None:
    """Record that these actions' summaries reached the vector store, at `embedding_version` when given."""
    updated: list[ActionModel] = []
    for action_id in action_ids:
        action = ActionModel(id=action_id, embedding_last_synced_at=synced_at)
        if embedding_version is not None:
            action.embedding_version = embedding_version
        updated.append(action)
    if not updated:
        return
    await ActionModel.objects.abulk_update(
        updated,
        ["embedding_last_synced_at", "embedding_version"]
        if embedding_version is not None
        else ["embedding_last_synced_at"],
    )
