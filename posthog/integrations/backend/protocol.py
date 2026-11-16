"""The storage primitives of the integrations SDK, and the plain data that they take and return.

The accessors apply the scope rules of the SDK (kinds, auth types, warehouse source rows, reserved
config keys) and call one `StorageBackend` for the rows. Every primitive must also work over HTTP,
so a primitive takes and returns plain data only: no querysets, no callbacks into caller code, and no
model instances that callers write.
"""

import builtins
import dataclasses
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Protocol

from posthog.dataclasses import frozen
from posthog.integrations.contracts import (
    ConfigValue,
    CrossTeamFilter,
    IntegrationPatch,
    IntegrationRecord,
    RepositoryCache,
    UpdatedRows,
)
from posthog.integrations.enums import AuthType
from posthog.integrations.observability import TokenRefreshResult


class SourceRows(Enum):
    # Named accessors skip warehouse source rows, so code that reads a kind in its usual shape never
    # gets a row with typed-in source credentials.
    EXCLUDE = "exclude"
    ONLY = "only"
    INCLUDE = "include"


@frozen
class KindScope:
    """The rows of one kind in a scope."""

    kind: str
    # None reads every auth type of the kind. A row without `config["auth_type"]` has the default
    # auth type of its kind.
    auth_types: frozenset[AuthType] | None = None


@frozen
class RowScope:
    """The rows that one accessor reaches."""

    # None reaches every kind. An empty tuple reaches no row.
    kinds: tuple[KindScope, ...] | None
    source_rows: SourceRows = SourceRows.EXCLUDE


@frozen
class RowFilter:
    """The rows of a scope that a read selects. The accessor checks `where` before the backend sees it.

    Set `team_id` or `team_ids`, or neither to select the rows of every team.
    """

    team_id: int | None = None
    # An empty tuple selects no row.
    team_ids: tuple[int, ...] | None = None
    external_id: str | None = None
    # Config keys compared with these values for equality, the JSON type included.
    where: Mapping[str, ConfigValue] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.team_id is not None and self.team_ids is not None:
            raise ValueError("A row filter takes team_id or team_ids, not both")


@frozen
class NewIntegration:
    """A row to create. The accessor already wrote `config["auth_type"]` when the auth type is not the default."""

    team_id: int
    kind: str
    external_id: str | None
    config: Mapping[str, object]
    sensitive_config: Mapping[str, object] = dataclasses.field(default_factory=dict, repr=False)
    created_by_id: int | None = None


@frozen
class TokenRefresh:
    """The row after a locked token refresh, and what the refresh did."""

    record: IntegrationRecord
    result: TokenRefreshResult


class StorageBackend(Protocol):
    """Where the integration rows live. Every read and write is limited to the rows in `scope`.

    A read by id raises `IntegrationNotFound` when the row is not in the scope or not in the team.
    Rows come back oldest first, ordered by `created_at` and then `id`.
    """

    def get(self, scope: RowScope, *, team_id: int, id: int) -> IntegrationRecord: ...

    def get_many(self, scope: RowScope, *, team_id: int, ids: Sequence[int]) -> dict[int, IntegrationRecord]: ...

    def find(self, scope: RowScope, row_filter: RowFilter) -> IntegrationRecord | None:
        """The oldest row that matches, or None."""
        ...

    def list(
        self, scope: RowScope, row_filter: RowFilter, *, newest_first: bool = False
    ) -> builtins.list[IntegrationRecord]: ...

    def exists(self, scope: RowScope, row_filter: RowFilter) -> bool: ...

    def count(self, scope: RowScope, row_filter: RowFilter) -> int: ...

    def count_by_external_ids(self, scope: RowScope, *, external_ids: Sequence[str]) -> dict[str, int]:
        """How many rows of every team have each external id. An external id without rows is not a key."""
        ...

    def get_by_external_id(self, scope: RowScope, *, external_id: str, id: int) -> IntegrationRecord:
        """The row of any team with this id and this external id."""
        ...

    def list_across_teams(
        self, scope: RowScope, cross_team_filter: CrossTeamFilter
    ) -> builtins.list[IntegrationRecord]:
        """The rows of every team that match the filter, ordered by id and not by `created_at`, so `after_id` can page."""
        ...

    def create(self, new: NewIntegration) -> IntegrationRecord:
        """Raises `IntegrationConflict` when the team has a row of the kind with this external id, in any scope."""
        ...

    def upsert(self, scope: RowScope, new: NewIntegration) -> tuple[IntegrationRecord, bool]:
        """Create the row, or replace the config and the sensitive config of the row with the same key.

        A replace also clears `errors`. `new.created_by_id=None` keeps the creator of an existing row.
        Returns True when the row is new. Raises `IntegrationConflict` when the existing row is not in
        the scope.
        """
        ...

    def update(self, scope: RowScope, *, team_id: int, id: int, patch: IntegrationPatch) -> IntegrationRecord:
        """Apply the patch under a row lock. A patch that changes nothing writes nothing."""
        ...

    def delete(self, scope: RowScope, *, team_id: int, id: int) -> None: ...

    def change_external_id(self, scope: RowScope, *, team_id: int, id: int, external_id: str) -> IntegrationRecord:
        """Give the row another external id under a row lock.

        Raises `IntegrationConflict` when the team has a row of the kind with that external id, in any scope.
        """
        ...

    def update_by_external_id(self, scope: RowScope, *, external_id: str, patch: IntegrationPatch) -> int:
        """Apply the patch to the rows of every team with this external id. Returns how many rows changed."""
        ...

    def delete_by_external_id(self, scope: RowScope, *, external_id: str) -> int:
        """Delete the rows of every team with this external id, all or none. Returns how many rows it deleted."""
        ...

    def refresh_access_token(
        self, scope: RowScope, *, team_id: int, id: int, stale_access_token: str | None
    ) -> TokenRefresh:
        """Lock the row, refresh its OAuth tokens when they expire soon or match `stale_access_token`, and store them.

        An empty `stale_access_token` matches a row without an access token. A failed refresh stores
        `errors` and does not raise. The lock stops two workers from spending the same refresh token.
        """
        ...

    def update_where(self, scope: RowScope, row_filter: RowFilter, patch: IntegrationPatch) -> UpdatedRows:
        """Apply the patch to every row that the filter selects, under row locks, all or none.

        A row that the patch does not change is not written. Each changed row is saved on its own, so
        the save signals fire.
        """
        ...

    def get_repository_cache(self, scope: RowScope, *, team_id: int, id: int) -> RepositoryCache: ...

    def set_repository_cache(
        self,
        scope: RowScope,
        *,
        team_id: int,
        id: int,
        repositories: builtins.list[dict[str, object]] | None,
        updated_at: datetime,
    ) -> None:
        """Store the time of a fetch, and the list when it is not None. None keeps the stored list."""
        ...

    def expire_repository_cache_by_external_id(self, scope: RowScope, *, external_id: str) -> int:
        """Mark the cached list of every team's row with this external id as stale. Returns how many rows it reached."""
        ...
