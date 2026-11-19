"""A model rename rewrites the models that read it, so the old name does not survive in any of them."""

import json
import uuid
import hashlib
from collections.abc import Callable

from django.db.models import Q, QuerySet

from posthog.hogql.database.database import Database, is_authored_model
from posthog.hogql.errors import BaseHogQLError

from posthog.dataclasses import frozen
from posthog.models import Team

from products.data_modeling.backend.facade.contracts import (
    ModelRenameBlocked,
    ModelRenameBlockedError,
    ModelRenamePlan,
    ModelRenamePlanStaleError,
    ModelRenameRefusedError,
    ModelRenameRewrite,
)
from products.data_modeling.backend.logic.incremental import carry_definition_fingerprint
from products.data_modeling.backend.logic.model_bindings import QueryBindings, binding_change, query_bindings
from products.data_modeling.backend.logic.model_references import (
    PARSE_CHECK_FAILED,
    ModelReferenceRewriteError,
    model_spellings,
    rename_model_references,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

MANAGED_VIEW_RENAME_REFUSAL = "Cannot update a query from a managed viewset"
ENDPOINT_VIEW_RENAME_REFUSAL = "This view belongs to an endpoint, so it cannot be renamed."


def _refusal(saved_query: DataWarehouseSavedQuery) -> str | None:
    if (
        saved_query.managed_viewset_id is not None
        or saved_query.origin == DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET
    ):
        return MANAGED_VIEW_RENAME_REFUSAL
    if saved_query.origin == DataWarehouseSavedQuery.Origin.ENDPOINT:
        return ENDPOINT_VIEW_RENAME_REFUSAL
    return None


def _candidates_filter(saved_query: DataWarehouseSavedQuery) -> Q:
    # A query that does not contain the old leaf name cannot reference the model, so it is never parsed.
    return Q(query__query__icontains=saved_query.name_chain[-1])


def _load(
    live_queries: QuerySet[DataWarehouseSavedQuery], saved_query_id: uuid.UUID, *, lock: bool
) -> tuple[DataWarehouseSavedQuery, list[DataWarehouseSavedQuery]]:
    """The renamed model and the models that may read it, ordered by id."""
    renamed = live_queries.get(pk=saved_query_id)
    if not lock:
        return renamed, list(live_queries.filter(_candidates_filter(renamed)).exclude(pk=renamed.pk).order_by("pk"))
    while True:
        # One statement in id order locks the model and its readers, so two concurrent renames cannot each hold
        # a row the other waits for. `FOR NO KEY UPDATE`: a concurrent materialization takes `KEY SHARE` on these
        # rows for its job's foreign key.
        rows = list(
            live_queries.filter(Q(pk=renamed.pk) | _candidates_filter(renamed))
            .order_by("pk")
            .select_for_update(no_key=True)
        )
        locked = next((row for row in rows if row.pk == renamed.pk), None)
        if locked is None:
            raise DataWarehouseSavedQuery.DoesNotExist()
        if locked.name == renamed.name:
            return locked, [row for row in rows if row.pk != renamed.pk]
        # Renamed since it was read, so the candidates were matched on a stale name.
        renamed = locked


@frozen
class _Rewrite:
    dependent: DataWarehouseSavedQuery
    before: str
    after: str


@frozen
class _ComputedRename:
    plan: ModelRenamePlan
    renamed: DataWarehouseSavedQuery
    rewrites: list[_Rewrite]


def _compute(team: Team, saved_query_id: uuid.UUID, new_name: str, *, lock: bool) -> _ComputedRename:
    live_queries = DataWarehouseSavedQuery.objects.filter(team_id=team.pk).exclude(deleted=True)
    renamed, candidates = _load(live_queries, saved_query_id, lock=lock)
    refusal = _refusal(renamed)
    if refusal is not None:
        raise ModelRenameRefusedError(refusal)
    # Which names bind to the model is a fact about the team, so it must not depend on what the caller can read.
    database = Database.create_for(team=team, bypass_warehouse_access_control=True)
    spellings = model_spellings(renamed, database)
    new_chain = new_name.split(".")

    spliced: list[_Rewrite] = []
    blocked: list[ModelRenameBlocked] = []
    fingerprint: list[list[str]] = []
    for dependent in candidates:
        # Raw Trino views are not HogQL, and machine-made views are rewritten by what makes them.
        if not is_authored_model(dependent) or not dependent.engine.has_lineage.available:
            continue
        # The stored text, not `dependent.sql`: that one binds the incremental window start.
        before = (dependent.query or {}).get("query")
        if not isinstance(before, str):
            continue
        try:
            after = rename_model_references(before, spellings, new_chain)
        except ModelReferenceRewriteError as error:
            blocked.append(ModelRenameBlocked(saved_query_id=dependent.id, name=dependent.name, reason=str(error)))
        else:
            if after == before:
                continue
            spliced.append(_Rewrite(dependent=dependent, before=before, after=after))
        fingerprint.append([str(dependent.id), str(dependent.query_revision), before])

    rewrites: list[_Rewrite] = []
    if spliced:
        # The splice proves only that the text changed where it meant to. Resolving each query before and after
        # proves every name still binds to the same table. All the "before" resolutions run first, on the catalog
        # they share, so a part of it built on first use is built once and carried into the renamed copy.
        current: dict[uuid.UUID, QueryBindings | None] = {}
        for rewrite in spliced:
            try:
                current[rewrite.dependent.pk] = query_bindings(team, rewrite.before, database)
            except BaseHogQLError:
                # It does not run today, so there is nothing to preserve.
                current[rewrite.dependent.pk] = None
        try:
            # Every rewrite is checked as if all of them landed: a rename applies only when none is blocked.
            renamed_database: Database | None = database.with_model_renamed(
                renamed.name, new_name, {rewrite.dependent.name: rewrite.after for rewrite in spliced}
            )
        except KeyError:
            renamed_database = None
        for rewrite in spliced:
            bindings = current[rewrite.dependent.pk]
            if renamed_database is None:
                reason: str | None = PARSE_CHECK_FAILED
            elif bindings is None:
                reason = None
            else:
                reason = binding_change(team, bindings, rewrite.after, renamed_database, renamed.name, new_name)
            if reason is None:
                rewrites.append(rewrite)
            else:
                blocked.append(
                    ModelRenameBlocked(saved_query_id=rewrite.dependent.id, name=rewrite.dependent.name, reason=reason)
                )

    token = hashlib.sha256(
        json.dumps([str(renamed.id), renamed.name, str(renamed.query_revision), new_name, fingerprint]).encode()
    ).hexdigest()
    plan = ModelRenamePlan(
        rewrites=tuple(
            ModelRenameRewrite(
                saved_query_id=rewrite.dependent.id,
                name=rewrite.dependent.name,
                before=rewrite.before,
                after=rewrite.after,
            )
            for rewrite in rewrites
        ),
        blocked=tuple(blocked),
        token=token,
    )
    return _ComputedRename(plan=plan, renamed=renamed, rewrites=rewrites)


def plan_model_rename(team: Team, saved_query_id: uuid.UUID, new_name: str) -> ModelRenamePlan:
    """What renaming the model to `new_name` changes in the models that read it. Writes nothing."""
    return _compute(team, saved_query_id, new_name, lock=False).plan


def _write_rewritten_query(dependent: DataWarehouseSavedQuery, sql: str) -> None:
    """Stores a query whose text changed and whose result did not.

    The new revision makes an editor that holds the old text conflict on save. Nothing that marks the
    model as modified is written, and the incremental fingerprint follows the text, so no run rebuilds.
    A queryset update, so the post-save receivers that react to a changed definition do not run.
    """
    previous_query: dict = dependent.query or {}
    dependent.query = {**previous_query, "query": sql}
    carry_definition_fingerprint(dependent, previous_query)
    DataWarehouseSavedQuery.objects.filter(team_id=dependent.team_id, pk=dependent.pk).update(
        query=dependent.query, query_revision=uuid.uuid4(), incremental_state=dependent.incremental_state
    )


def apply_model_rename(
    team: Team,
    saved_query_id: uuid.UUID,
    new_name: str,
    plan_token: str,
    *,
    authorize: Callable[[ModelRenamePlan], None],
) -> ModelRenamePlan:
    """Renames the model to `new_name` and rewrites the models that read it, or writes nothing.

    Call it in a transaction. It locks the model and the models that read it, and writes only when the
    plan is still the one the caller was shown and `authorize` accepts it without raising.
    """
    computed = _compute(team, saved_query_id, new_name, lock=True)
    plan = computed.plan
    if plan.token != plan_token:
        raise ModelRenamePlanStaleError()
    authorize(plan)
    if plan.blocked:
        raise ModelRenameBlockedError(plan)
    for rewrite in computed.rewrites:
        _write_rewritten_query(rewrite.dependent, rewrite.after)
    computed.renamed.name = new_name
    computed.renamed.save(update_fields=["name", "updated_at"])
    return plan


def rename_needs_plan(team: Team, saved_query_id: uuid.UUID, new_name: str) -> bool:
    """Whether renaming the model to `new_name` changes or is blocked by a model that reads it.

    Call it in the transaction that renames the model: it locks the same rows as `apply_model_rename`,
    so a model that starts reading this one cannot commit until the rename has.
    """
    try:
        plan = _compute(team, saved_query_id, new_name, lock=True).plan
    except ModelRenameRefusedError:
        return False
    return bool(plan.rewrites or plan.blocked)
