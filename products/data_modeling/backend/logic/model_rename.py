"""A model rename rewrites the models that read it, so the old name does not survive in any of them."""

import json
import uuid
import hashlib
from collections.abc import Callable

from posthog.hogql.database.database import Database, is_authored_model

from posthog.models import Team

from products.data_modeling.backend.facade.contracts import (
    ModelRenameBlocked,
    ModelRenameBlockedError,
    ModelRenamePlan,
    ModelRenamePlanStaleError,
    ModelRenameRewrite,
)
from products.data_modeling.backend.logic.incremental import carry_definition_fingerprint
from products.data_modeling.backend.logic.model_references import (
    ModelReferenceRewriteError,
    model_spellings,
    rename_model_references,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


def _compute(
    team: Team, saved_query_id: uuid.UUID, new_name: str, *, lock: bool
) -> tuple[ModelRenamePlan, DataWarehouseSavedQuery, list[tuple[DataWarehouseSavedQuery, str, str]]]:
    live_queries = DataWarehouseSavedQuery.objects.filter(team_id=team.pk).exclude(deleted=True)
    if lock:
        # `FOR NO KEY UPDATE`: a concurrent materialization takes `KEY SHARE` on these rows for its job's foreign key.
        live_queries = live_queries.select_for_update(no_key=True)
    renamed = live_queries.get(pk=saved_query_id)
    # Which names bind to the model is a fact about the team, so it must not depend on what the caller can read.
    spellings = model_spellings(renamed, Database.create_for(team=team, bypass_warehouse_access_control=True))
    new_chain = new_name.split(".")

    # A query that does not contain the old leaf name cannot reference the model, so it is never parsed.
    candidates = live_queries.filter(query__query__icontains=renamed.name_chain[-1]).exclude(pk=renamed.pk)
    rewrites: list[tuple[DataWarehouseSavedQuery, str, str]] = []
    blocked: list[ModelRenameBlocked] = []
    fingerprint: list[list[str]] = []
    for dependent in candidates.order_by("id"):
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
            rewrites.append((dependent, before, after))
        fingerprint.append([str(dependent.id), str(dependent.query_revision), before])

    token = hashlib.sha256(
        json.dumps([str(renamed.id), renamed.name, str(renamed.query_revision), new_name, fingerprint]).encode()
    ).hexdigest()
    plan = ModelRenamePlan(
        rewrites=tuple(
            ModelRenameRewrite(saved_query_id=dependent.id, name=dependent.name, before=before, after=after)
            for dependent, before, after in rewrites
        ),
        blocked=tuple(blocked),
        token=token,
    )
    return plan, renamed, rewrites


def plan_model_rename(team: Team, saved_query_id: uuid.UUID, new_name: str) -> ModelRenamePlan:
    """What renaming the model to `new_name` changes in the models that read it. Writes nothing."""
    plan, _, _ = _compute(team, saved_query_id, new_name, lock=False)
    return plan


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
    plan, renamed, rewrites = _compute(team, saved_query_id, new_name, lock=True)
    if plan.token != plan_token:
        raise ModelRenamePlanStaleError()
    authorize(plan)
    if plan.blocked:
        raise ModelRenameBlockedError(plan)
    for dependent, _, sql in rewrites:
        _write_rewritten_query(dependent, sql)
    renamed.name = new_name
    renamed.save(update_fields=["name", "updated_at"])
    return plan


def rename_needs_plan(team: Team, saved_query_id: uuid.UUID, new_name: str) -> bool:
    """Whether renaming the model to `new_name` changes or is blocked by a model that reads it.

    Call it in the transaction that renames the model: it locks the same rows as `apply_model_rename`,
    so a model that starts reading this one cannot commit until the rename has.
    """
    plan, _, _ = _compute(team, saved_query_id, new_name, lock=True)
    return bool(plan.rewrites or plan.blocked)
