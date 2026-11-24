from collections.abc import Mapping, Sequence

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import FieldOrTable, LazyJoin, SavedQuery
from posthog.hogql.errors import QueryError, ResolutionError

from products.data_modeling.backend.facade.contracts import ModelRenameJoin


def renamed_catalog(
    database: Database,
    old_name: str,
    new_name: str,
    rewritten_queries: Mapping[str, str] | None = None,
    renamed_joins: Sequence[ModelRenameJoin] = (),
) -> Database:
    """A copy of `database` in which the authored model stored as `old_name` answers to `new_name` and
    `models.<new_name>`, and no longer to its old names, as if the catalog were built after the rename. Each
    authored model named in `rewritten_queries` reads as its rewritten query, so a model that reads it expands
    the new text. The model's join fields move with it, as the rename moves its saved joins, and each join in
    `renamed_joins` whose joining side changes reads the renamed model under its new name.

    The copy costs no catalog build, and `database` is left as it was. Raises KeyError when `old_name` is not
    an authored model.
    """
    model_node = database.authored_model_node(old_name)
    if model_node is None:
        raise KeyError(old_name)
    model = model_node.table
    # The resolver names a model's rows after its table, so the copy carries the new name. A materialized
    # model's table is named after its backing table, which a rename does not move.
    if isinstance(model, SavedQuery):
        # Its own fields, so a join from the model to itself can be repointed without touching `database`.
        model = model.model_copy(update={"name": new_name, "fields": dict(model.fields)})
    renamed = database.shallow_copy()
    renamed.move_model(old_name, new_name, model)
    # Before the rewrites, so a rewritten model that is a join's source copies the repointed join.
    for join in renamed_joins:
        if join.joining_table_name_after != join.joining_table_name_before:
            _repoint_join_into_model(renamed, join, model)
    for name, query in (rewritten_queries or {}).items():
        view_node = renamed.authored_model_node(name)
        if view_node is None or view_node.table is None:
            continue
        renamed.replace_table(name.split("."), view_node.table, view_node.table.model_copy(update={"query": query}))
    return renamed


def _repoint_join_into_model(database: Database, join: ModelRenameJoin, model: FieldOrTable | None) -> None:
    """Points the join field at the renamed model, as the catalog build does after the rename. A join resolves
    its table by the stored name, so a field still naming the old one fails once printed."""
    chain = join.source_table_name_after.split(".")
    try:
        source = database.get_table(chain)
    except (ResolutionError, QueryError):
        return
    field = source.fields.get(join.field_name)
    if not isinstance(field, LazyJoin) or "joining_table_name" not in field.resolver_params:
        return
    repointed = field.model_copy(
        update={
            "join_table": join.joining_table_name_after if isinstance(field.join_table, str) else model,
            "resolver_params": {**field.resolver_params, "joining_table_name": join.joining_table_name_after},
        }
    )
    if source is model:
        source.fields[join.field_name] = repointed
        return
    database.replace_table(
        chain, source, source.model_copy(update={"fields": {**source.fields, join.field_name: repointed}})
    )
