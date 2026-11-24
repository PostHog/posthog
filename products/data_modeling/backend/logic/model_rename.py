"""A model rename rewrites the models that read it, so the old name does not survive in any of them."""

import json
import uuid
import hashlib
from collections.abc import Callable

from django.db.models import Q, QuerySet

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.compilation import CompilationBudget, compilation_budget
from posthog.hogql.database.database import Database, JoinIntoModel, is_authored_model
from posthog.hogql.errors import BaseHogQLError, CompilationBudgetExceededError

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

from products.data_modeling.backend.facade.contracts import (
    ModelRenameBlocked,
    ModelRenameBlockedError,
    ModelRenameJoin,
    ModelRenamePlan,
    ModelRenamePlanStaleError,
    ModelRenameRefusedError,
    ModelRenameRewrite,
    ModelRenameTooLargeError,
)
from products.data_modeling.backend.logic.incremental import carry_definition_fingerprint
from products.data_modeling.backend.logic.model_bindings import (
    DOES_NOT_RUN,
    QueryBindings,
    binding_change,
    query_bindings,
)
from products.data_modeling.backend.logic.model_references import (
    PARSE_CHECK_FAILED,
    Chain,
    ModelReferenceRewriteError,
    binds_to_model,
    model_spellings,
    rename_model_references,
    renamed_chain,
    table_reads,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_tools.backend.facade.models import DataWarehouseJoin

MANAGED_VIEW_RENAME_REFUSAL = "Cannot update a query from a managed viewset"
ENDPOINT_VIEW_RENAME_REFUSAL = "This view belongs to an endpoint, so it cannot be renamed."
TOO_MANY_VIEWS_TO_CHECK = "This rename affects too many views to check at once."


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
    joins: list[DataWarehouseJoin]


def _load_joins(team: Team, spellings: set[Chain], *, lock: bool) -> list[DataWarehouseJoin]:
    """The saved joins with a side whose name binds to the model, ordered by id.

    By spelling, not stored name: a synced table can hold the model's bare name, and its joins are its own.
    """
    names = [".".join(chain) for chain in spellings]
    joins = (
        DataWarehouseJoin.objects.filter(team_id=team.pk)
        .filter(Q(source_table_name__in=names) | Q(joining_table_name__in=names))
        .exclude(deleted=True)
        .order_by("pk")
    )
    return list(joins.select_for_update(no_key=True) if lock else joins)


def _renamed_join(join: DataWarehouseJoin, spellings: set[Chain], new_chain: list[str]) -> ModelRenameJoin:
    def renamed(name: str) -> str:
        chain = tuple(name.split("."))
        return ".".join(renamed_chain(chain, new_chain)) if chain in spellings else name

    return ModelRenameJoin(
        join_id=join.id,
        field_name=join.field_name,
        source_table_name_before=join.source_table_name,
        source_table_name_after=renamed(join.source_table_name),
        joining_table_name_before=join.joining_table_name,
        joining_table_name_after=renamed(join.joining_table_name),
    )


def _renamed_join_destinations(
    renamed: DataWarehouseSavedQuery, joins: list[ModelRenameJoin], renamed_database: Database | None
) -> list[ModelRenameBlocked]:
    """A changed side of a join must bind to the renamed model after the rename. Another model can be stored
    under the new spelling, such as `models.<new name>`, and the join would then read that model."""
    blocked: list[ModelRenameBlocked] = []
    for join in joins:
        for before, after in [
            (join.source_table_name_before, join.source_table_name_after),
            (join.joining_table_name_before, join.joining_table_name_after),
        ]:
            if before == after:
                continue
            if renamed_database is None or not binds_to_model(after.split("."), renamed, renamed_database):
                blocked.append(
                    ModelRenameBlocked(
                        saved_query_id=renamed.id,
                        name=renamed.name,
                        reason=(
                            f"After the rename, its join {join.field_name} would read {after}, "
                            "which is a different table."
                        ),
                    )
                )
    return blocked


def _readers_hiding_a_name(
    live_queries: QuerySet[DataWarehouseSavedQuery],
    database: Database,
    renamed: DataWarehouseSavedQuery,
    dependents: list[DataWarehouseSavedQuery],
    names: set[str],
) -> list[ModelRenameBlocked]:
    """The models that read a rewritten model, directly or through others, with a CTE named one of `names` in
    scope there.

    A model's expanded body sees the CTEs in scope where it is read. A CTE with the old name stands in for the
    model in the body before the rename, and one with the new name stands in after it. The binding check sees
    only a query's own references, not those.
    """
    budget = compilation_budget.get()
    # Every model is parsed once, into the readers of each table name it reads.
    readers_of: dict[Chain, list[tuple[DataWarehouseSavedQuery, str | None]]] = {}
    for model in live_queries:
        text = (model.query or {}).get("query")
        if not is_authored_model(model) or not isinstance(text, str):
            continue
        if budget is not None:
            budget.check_time()
        for table_read in table_reads(text, names):
            readers_of.setdefault(table_read.chain, []).append((model, table_read.watched_cte))

    reached = {renamed.pk, *(dependent.pk for dependent in dependents)}
    frontier = list(dependents)
    blocked: dict[uuid.UUID, ModelRenameBlocked] = {}
    while frontier:
        if budget is not None:
            budget.check_time()
        read = frontier.pop()
        for spelling in model_spellings(read, database):
            for reader, cte in readers_of.get(spelling, []):
                if cte is not None and reader.pk not in blocked:
                    blocked[reader.pk] = ModelRenameBlocked(
                        saved_query_id=reader.id,
                        name=reader.name,
                        reason=f"It defines a CTE named {cte}, so the rename would change what a view it reads returns.",
                    )
                if reader.pk not in reached:
                    reached.add(reader.pk)
                    frontier.append(reader)
    return list(blocked.values())


def _renamed_catalog(
    database: Database,
    old_name: str,
    new_name: str,
    rewritten_queries: dict[str, str],
    renamed_joins: list[ModelRenameJoin],
) -> Database | None:
    joins_into_model = [
        JoinIntoModel(
            source_table_name=join.source_table_name_after,
            field_name=join.field_name,
            joining_table_name=join.joining_table_name_after,
        )
        for join in renamed_joins
        if join.joining_table_name_after != join.joining_table_name_before
    ]
    try:
        return database.with_model_renamed(old_name, new_name, rewritten_queries, joins_into_model)
    except KeyError:
        return None


def _compute(team: Team, saved_query_id: uuid.UUID, new_name: str, *, lock: bool) -> _ComputedRename:
    # One budget for every resolve, so a large plan stops at one deadline instead of one per query.
    token = compilation_budget.set(CompilationBudget())
    try:
        return _compute_within_budget(team, saved_query_id, new_name, lock=lock)
    except CompilationBudgetExceededError as error:
        raise ModelRenameTooLargeError(TOO_MANY_VIEWS_TO_CHECK) from error
    finally:
        compilation_budget.reset(token)


def _compute_within_budget(team: Team, saved_query_id: uuid.UUID, new_name: str, *, lock: bool) -> _ComputedRename:
    live_queries = DataWarehouseSavedQuery.objects.filter(team_id=team.pk).exclude(deleted=True)
    renamed, candidates = _load(live_queries, saved_query_id, lock=lock)
    refusal = _refusal(renamed)
    if refusal is not None:
        raise ModelRenameRefusedError(refusal)
    # Which names bind to the model is a fact about the team, so it must not depend on what the caller can read.
    # Each model reads as its query, not as its materialized table, so its name is the model's, not the table's.
    database = Database.create_for(
        team=team, modifiers=HogQLQueryModifiers(useMaterializedViews=False), bypass_warehouse_access_control=True
    )
    spellings = model_spellings(renamed, database)
    new_chain = new_name.split(".")
    joins = _load_joins(team, spellings, lock=lock)
    renamed_joins = [_renamed_join(join, spellings, new_chain) for join in joins]

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
        current: dict[uuid.UUID, QueryBindings] = {}
        failed_expanded: list[_Rewrite] = []
        for rewrite in spliced:
            try:
                current[rewrite.dependent.pk] = query_bindings(team, rewrite.before, database)
            except CompilationBudgetExceededError:
                raise
            except BaseHogQLError:
                failed_expanded.append(rewrite)
        # A materialized model serves its stored rows even when its body no longer runs, so its readers still
        # work. They are checked against the catalog that serves those rows.
        serving: dict[uuid.UUID, QueryBindings | None] = {}
        serving_database: Database | None = None
        if failed_expanded:
            serving_database = Database.create_for(team=team, bypass_warehouse_access_control=True)
            for rewrite in failed_expanded:
                try:
                    serving[rewrite.dependent.pk] = query_bindings(team, rewrite.before, serving_database)
                except CompilationBudgetExceededError:
                    raise
                except BaseHogQLError:
                    serving[rewrite.dependent.pk] = None
        rewritten_queries = {rewrite.dependent.name: rewrite.after for rewrite in spliced}
        # Every rewrite is checked as if all of them landed: a rename applies only when none is blocked.
        renamed_database = _renamed_catalog(database, renamed.name, new_name, rewritten_queries, renamed_joins)
        renamed_serving_database = (
            _renamed_catalog(serving_database, renamed.name, new_name, rewritten_queries, renamed_joins)
            if serving_database is not None
            else None
        )
        for rewrite in spliced:
            pk = rewrite.dependent.pk
            reason: str | None
            if pk in current:
                check: QueryBindings | None = current[pk]
                against = renamed_database
            else:
                check, against = serving[pk], renamed_serving_database
            if against is None:
                reason = PARSE_CHECK_FAILED
            elif check is None:
                reason = DOES_NOT_RUN
            else:
                reason = binding_change(team, check, rewrite.after, against)
            if reason is None:
                rewrites.append(rewrite)
            else:
                blocked.append(
                    ModelRenameBlocked(saved_query_id=rewrite.dependent.id, name=rewrite.dependent.name, reason=reason)
                )

    if rewrites:
        # The CTE names that can stand in for the model: each spelling, before and after the rename.
        hiding_names = {new_chain[0]}
        for spelling in spellings:
            hiding_names |= {".".join(spelling), ".".join(renamed_chain(spelling, new_chain))}
        already_blocked = {entry.saved_query_id for entry in blocked}
        blocked.extend(
            entry
            for entry in _readers_hiding_a_name(
                live_queries, database, renamed, [rewrite.dependent for rewrite in rewrites], hiding_names
            )
            if entry.saved_query_id not in already_blocked
        )
    if renamed_joins:
        blocked.extend(
            _renamed_join_destinations(
                renamed, renamed_joins, _renamed_catalog(database, renamed.name, new_name, {}, renamed_joins)
            )
        )

    join_fingerprint = [
        [str(join.join_id), join.field_name, join.source_table_name_before, join.joining_table_name_before]
        for join in renamed_joins
    ]
    token = hashlib.sha256(
        json.dumps(
            [str(renamed.id), renamed.name, str(renamed.query_revision), new_name, fingerprint, join_fingerprint]
        ).encode()
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
        joins=tuple(renamed_joins),
        token=token,
    )
    return _ComputedRename(plan=plan, renamed=renamed, rewrites=rewrites, joins=joins)


def plan_model_rename(team: Team, saved_query_id: uuid.UUID, new_name: str) -> ModelRenamePlan:
    """What renaming the model to `new_name` changes in the models that read it and the joins that name it.

    Writes nothing.
    """
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
    user: User | None = None,
    was_impersonated: bool = False,
) -> ModelRenamePlan:
    """Renames the model to `new_name`, rewrites the models that read it and renames the joins that name it,
    or writes nothing. Each rewritten model gets an activity entry for `user`.

    Call it in a transaction. It locks the model, the models that read it and those joins, and writes only
    when the plan is still the one the caller was shown and `authorize` accepts it without raising.
    """
    computed = _compute(team, saved_query_id, new_name, lock=True)
    plan = computed.plan
    if plan.token != plan_token:
        raise ModelRenamePlanStaleError()
    authorize(plan)
    if plan.blocked:
        raise ModelRenameBlockedError(plan)
    for rewrite in computed.rewrites:
        before_query = dict(rewrite.dependent.query or {})
        _write_rewritten_query(rewrite.dependent, rewrite.after)
        # The rewrite is a queryset update, which no activity receiver sees.
        log_activity(
            organization_id=team.organization_id,
            team_id=team.pk,
            user=user,
            was_impersonated=was_impersonated,
            item_id=rewrite.dependent.pk,
            scope="DataWarehouseSavedQuery",
            activity="updated",
            detail=Detail(
                name=rewrite.dependent.name,
                changes=[
                    Change(
                        type="DataWarehouseSavedQuery",
                        action="changed",
                        field="query",
                        before=before_query,
                        after=rewrite.dependent.query,
                    )
                ],
            ),
        )
    for join, renamed_join in zip(computed.joins, plan.joins, strict=True):
        join.source_table_name = renamed_join.source_table_name_after
        join.joining_table_name = renamed_join.joining_table_name_after
        # A save, not a queryset update, so the join's activity log records the rename.
        join.save(update_fields=["source_table_name", "joining_table_name"])
    computed.renamed.name = new_name
    computed.renamed.save(update_fields=["name", "updated_at"])
    return plan


def rename_needs_plan(team: Team, saved_query_id: uuid.UUID, new_name: str) -> bool:
    """Whether renaming the model to `new_name` changes or is blocked by a model that reads it, or changes a join.

    Call it in the transaction that renames the model: it locks the same rows as `apply_model_rename`,
    so a model that starts reading this one cannot commit until the rename has.
    """
    try:
        plan = _compute(team, saved_query_id, new_name, lock=True).plan
    except ModelRenameTooLargeError:
        return True
    except ModelRenameRefusedError:
        return False
    return bool(plan.rewrites or plan.blocked or plan.joins)
