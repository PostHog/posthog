from typing import Optional

from posthog.hogql.database.models import LazyTable

from posthog.scopes import APIScopeObject


class ScopedLazyTable(LazyTable):
    """A system table built from a select over other system tables, gated by `access_scope` like a
    `PostgresTable` is.

    The gate is resource-level only. Row filtering, team scoping and object-level guards come from
    the system tables its select reads, so each of those must carry the same scope.
    """

    access_scope: APIScopeObject

    @property
    def access_control_id(self) -> Optional[str]:
        # No column keys an object grant, so a reader with only object grants on the scope is denied
        # the table rather than shown rows that no grant narrowed.
        return None
