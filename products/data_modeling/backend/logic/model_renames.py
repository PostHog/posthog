import copy
import json
import uuid
import hashlib
from collections.abc import Sequence
from uuid import UUID

from django.db.models import Q, QuerySet

from posthog.hogql.database.database import Database, qualify_model_name
from posthog.hogql.database.models import SavedQuery
from posthog.hogql.errors import BaseHogQLError

from posthog.dataclasses import frozen

from products.data_modeling.backend.logic.incremental import (
    TRINO_INCREMENTAL_SCOPE,
    definition_fingerprint,
    get_incremental_config,
)
from products.data_modeling.backend.logic.model_references import ModelReferenceRewriteError, rewrite_model_references
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


@frozen
class ModelRenameDependent:
    id: UUID
    name: str
    before: str
    after: str


@frozen
class ModelRenameBlocked:
    id: UUID
    name: str
    reason: str


@frozen
class ModelRenamePlan:
    dependents: list[ModelRenameDependent]
    blocked: list[ModelRenameBlocked]
    plan_token: str


def rename_candidates(team_id: int) -> QuerySet[DataWarehouseSavedQuery]:
    return (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, managed_viewset__isnull=True)
        .exclude(deleted=True)
        .filter(Q(origin__isnull=True) | Q(origin=DataWarehouseSavedQuery.Origin.DATA_WAREHOUSE))
        .order_by("id")
    )


def plan_model_rename(
    source: DataWarehouseSavedQuery,
    new_name: str,
    candidates: Sequence[DataWarehouseSavedQuery],
    database: Database,
) -> ModelRenamePlan:
    old = source.name.removeprefix("models.")
    new = tuple(qualify_model_name(new_name).split("."))
    spellings: set[tuple[str, ...]] = set()
    for spelling in (old, f"models.{old}"):
        try:
            table = database.get_table(spelling.split("."))
        except BaseHogQLError:
            continue
        table_id = table.id if isinstance(table, SavedQuery) else getattr(table, "saved_query_id", None)
        if table_id == str(source.pk):
            spellings.add(tuple(spelling.split(".")))

    dependents: list[ModelRenameDependent] = []
    blocked: list[ModelRenameBlocked] = []
    revisions: list[tuple[str, str]] = []
    for dependent in candidates:
        if dependent.pk == source.pk or not dependent.engine.has_lineage.available:
            continue
        sql = (dependent.query or {}).get("query")
        if not isinstance(sql, str) or old.split(".")[-1] not in sql:
            continue
        try:
            rewritten = rewrite_model_references(sql, spellings, new)
        except ModelReferenceRewriteError as error:
            blocked.append(ModelRenameBlocked(id=dependent.pk, name=dependent.name, reason=str(error)))
        else:
            if rewritten == sql:
                continue
            dependents.append(ModelRenameDependent(id=dependent.pk, name=dependent.name, before=sql, after=rewritten))
        revisions.append((str(dependent.pk), str(dependent.query_revision)))

    # Bind the confirmation to the source, destination and identity spellings as well as editor revisions.
    payload = [str(source.pk), source.name, str(source.query_revision), new, sorted(spellings), sorted(revisions)]
    token = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    return ModelRenamePlan(dependents=dependents, blocked=blocked, plan_token=token)


def write_model_reference_rewrite(view: DataWarehouseSavedQuery, sql: str) -> None:
    query = {**view.query, "query": sql}
    updates = {"query": query, "query_revision": uuid.uuid4()}
    config = get_incremental_config(view)
    if config is not None and isinstance(view.incremental_state, dict):
        previous_fingerprint = definition_fingerprint(view.query, config)
        next_fingerprint = definition_fingerprint(query, config)
        state = copy.deepcopy(view.incremental_state)
        # A rename must not turn an already stale definition into an incremental run.
        for progress in (state, state.get(TRINO_INCREMENTAL_SCOPE)):
            if (
                isinstance(progress, dict)
                and previous_fingerprint is not None
                and progress.get("definition_fingerprint") == previous_fingerprint
            ):
                progress["definition_fingerprint"] = next_fingerprint
        updates["incremental_state"] = state
    DataWarehouseSavedQuery.objects.filter(team_id=view.team_id, pk=view.pk).update(**updates)
