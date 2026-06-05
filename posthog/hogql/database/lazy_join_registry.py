from collections.abc import Callable
from typing import TYPE_CHECKING

from posthog.hogql.database import lazy_join_tags as tags
from posthog.hogql.database.warehouse_join_resolvers import (
    resolve_data_warehouse_experiments_join,
    resolve_data_warehouse_join,
    resolve_foreign_key_join,
)

if TYPE_CHECKING:
    from posthog.hogql import ast
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.database.models import LazyJoinToAdd

# A lazy-join resolver builds the JOIN ``ast.JoinExpr`` for a lazy join from plain data —
# the LazyJoin's ``from_field``/``to_field``/``resolver_params`` — plus the runtime
# resolution context and the query node. Resolvers are keyed by tag so a ``LazyJoin`` can
# describe its join declaratively (a tag + params) instead of carrying a Python closure,
# which is what makes a built ``Database`` serializable.
LazyJoinResolver = Callable[["LazyJoinToAdd", "HogQLContext", "ast.SelectQuery"], "ast.JoinExpr"]

# The explicit, closed list of every lazy-join resolver the engine supports. This is the
# contract a serialized Database depends on: a consumer (another process, a cache reader, a
# future non-Python engine) must implement exactly these tags. Add new resolvers here — a
# tag that isn't listed cannot be resolved.
RESOLVERS: dict[str, LazyJoinResolver] = {
    tags.FOREIGN_KEY: resolve_foreign_key_join,
    tags.DATA_WAREHOUSE: resolve_data_warehouse_join,
    tags.DATA_WAREHOUSE_EXPERIMENTS: resolve_data_warehouse_experiments_join,
}


def get_lazy_join_resolver(name: str) -> LazyJoinResolver:
    try:
        return RESOLVERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown lazy join resolver {name!r}. Every supported resolver must be listed in RESOLVERS."
        ) from None
