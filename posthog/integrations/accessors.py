"""The operations of the integrations SDK.

An accessor holds a scope: the kinds, the auth type, and whether it sees warehouse source rows. Every
operation reads or writes only rows in that scope. No accessor sees warehouse source rows unless the
caller asks for them with `with_source_rows()` or uses `IntegrationManager.source(kind)`.
`IntegrationReader` has the reads and the deletes. `AuthAccessor` adds the writes, and exists only for
one kind with one auth type, because a new row has exactly one auth type. `OAuthAccessor` adds the
token refresh.

No operation returns a queryset, and no operation runs caller code inside its transaction. The
integration rows move to a separate service later, so the operations here are the whole contract, and
only their transport changes. Rows come back typed as the read-only `IntegrationRecord`.
"""

import re
import json
import builtins
from collections.abc import Iterable, Mapping
from enum import Enum
from typing import ClassVar, Literal

from django.db import IntegrityError, transaction
from django.db.models import Q

from posthog.integrations.catalogue import KINDS
from posthog.integrations.contracts import (
    SOURCE_MARKER_CONFIG_KEY,
    ConfigValue,
    IntegrationConflict,
    IntegrationInUse,
    IntegrationNotFound,
    IntegrationPatch,
    IntegrationRecord,
    IntegrationUsage,
    UnknownIntegrationKind,
    UnsupportedAuthType,
    UnsupportedIntegrationFilter,
)
from posthog.integrations.enums import AuthType
from posthog.integrations.observability import instrumented, record_token_refresh
from posthog.integrations.source_kinds import is_source_kind
from posthog.integrations.usages import integration_usages
from posthog.models.integration.auth_types import ANY, AUTH_TYPE_CONFIG_KEY, default_auth_type, kind_auth_types
from posthog.models.integration.model import Integration, IntegrationQuerySet, defer_repository_cache_fields
from posthog.models.integration.oauth import OauthIntegration
from posthog.sync import database_sync_to_async

# The SDK writes these keys itself. A caller cannot set, remove or filter on them.
RESERVED_CONFIG_KEYS = frozenset({AUTH_TYPE_CONFIG_KEY, SOURCE_MARKER_CONFIG_KEY})

_CONFIG_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
# The unique key of a row: (team, kind, external id).
_UNIQUE_KEY_CONSTRAINT = "posthog_integration_kind_id_unique"
_SCALAR_TYPES = (str, int, float, bool, type(None))


class SourceRows(Enum):
    # Named accessors skip warehouse source rows, so code that reads a kind in its usual shape never
    # gets a row with typed-in source credentials.
    EXCLUDE = "exclude"
    ONLY = "only"
    INCLUDE = "include"


def _rows() -> IntegrationQuerySet:
    # The GitHub repository cache can be large. Django loads a deferred column when code reads it.
    return defer_repository_cache_fields(Integration.objects._with_auth(ANY))


# The auth types an accessor reads: one auth type, several, or the default auth type of each kind.
AuthTypes = AuthType | frozenset[AuthType] | Literal["default"]


def _auth_type_q(kind: str, auth_type: AuthType) -> Q:
    stored = Q(config__auth_type=auth_type.value)
    if auth_type == default_auth_type(kind):
        # A JSON null counts as unset, the same as in `auth_types.rows_with_default_auth_type_q`. A
        # stored default is possible too: `QuerySet.update()` skips the `normalized_config` of `save()`.
        return Q(config__auth_type__isnull=True) | Q(config__auth_type=None) | stored
    return stored


def _where_q(where: Mapping[str, ConfigValue] | None) -> Q:
    q = Q()
    for key, value in (where or {}).items():
        if not isinstance(key, str) or not _CONFIG_KEY.match(key) or "__" in key or key in RESERVED_CONFIG_KEYS:
            raise UnsupportedIntegrationFilter(f"Cannot filter integrations on the config key {key!r}")
        if not isinstance(value, _SCALAR_TYPES):
            raise UnsupportedIntegrationFilter(f"Cannot compare the config key {key!r} with a {type(value).__name__}")
        # `__exact`, so a key named like a lookup (`contains`, `regex`) still reads as a key.
        # nosemgrep: orm-field-injection - the key is one checked JSON key segment, and `__exact` fixes the lookup
        q &= Q(**{f"config__{key}__exact": value})
    return q


def _is_unique_key_violation(error: IntegrityError) -> bool:
    constraint = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
    return constraint == _UNIQUE_KEY_CONSTRAINT or _UNIQUE_KEY_CONSTRAINT in str(error)


def _checked_config_keys(keys: Iterable[str]) -> None:
    reserved = sorted(RESERVED_CONFIG_KEYS.intersection(keys))
    if reserved:
        raise ValueError(f"The integrations SDK writes {reserved} itself")


def _patched(
    current: Mapping[str, object] | None, patch: Mapping[str, object], remove: Iterable[str]
) -> dict[str, object]:
    result = dict(current or {})
    result.update(patch)
    for key in remove:
        result.pop(key, None)
    return result


class IntegrationReader:
    """Reads and deletes of the integration rows in one scope."""

    def __init__(
        self,
        *,
        kinds: frozenset[str] | None,
        auth_type: AuthTypes | None = None,
        source_rows: SourceRows = SourceRows.EXCLUDE,
    ) -> None:
        """`auth_type=None` reads every auth type. `"default"` reads the default auth type of each kind."""
        if auth_type is not None and not kinds:
            raise ValueError("An accessor with an auth type needs its kinds")
        self._kinds = kinds
        self._auth_type = auth_type
        self._source_rows = source_rows

    def _auth_types_of(self, kind: str) -> builtins.list[AuthType]:
        if self._auth_type == "default":
            return [default_auth_type(kind)]
        if isinstance(self._auth_type, AuthType):
            return [self._auth_type]
        if isinstance(self._auth_type, frozenset):
            return sorted(self._auth_type)
        return []

    def __repr__(self) -> str:
        kinds = sorted(self._kinds) if self._kinds is not None else "every kind"
        return f"{type(self).__name__}({kinds}, {self._auth_type or 'any auth type'}, {self._source_rows.value})"

    def _scope_q(self) -> Q:
        q = Q()
        if self._kinds is not None:
            if self._auth_type is None:
                q &= Q(kind__in=sorted(self._kinds))
            else:
                # An empty Q() in an OR matches every row, so start from a clause that matches none.
                by_kind = Q(pk__in=[])
                for kind in sorted(self._kinds):
                    for auth_type in self._auth_types_of(kind):
                        by_kind |= Q(kind=kind) & _auth_type_q(kind, auth_type)
                q &= by_kind
        if self._source_rows == SourceRows.EXCLUDE:
            q &= ~Q(config__has_key=SOURCE_MARKER_CONFIG_KEY)
        elif self._source_rows == SourceRows.ONLY:
            q &= Q(config__has_key=SOURCE_MARKER_CONFIG_KEY)
        return q

    def _cross_team_rows(self, operation: str) -> IntegrationQuerySet:
        # A cross-team operation without a kind would reach every row with the external id, of any
        # provider, in every team. External ids are only unique per provider.
        if self._kinds is None:
            raise ValueError(f"{operation} needs an accessor with a kind, such as IntegrationManager.github.oauth")
        return _rows().filter(self._scope_q())

    def _team_rows(self, team_id: int) -> IntegrationQuerySet:
        return _rows().filter(self._scope_q(), team_id=team_id)

    def _rows_of_teams(self, team_id: int | None, team_ids: Iterable[int] | None) -> IntegrationQuerySet:
        if (team_id is None) == (team_ids is None):
            raise ValueError("Pass exactly one of team_id and team_ids")
        if team_id is not None:
            return self._team_rows(team_id)
        # An empty list matches no row.
        return _rows().filter(self._scope_q(), team_id__in=builtins.list(team_ids or ()))

    def _matching(
        self,
        team_id: int | None,
        external_id: str | None,
        where: Mapping[str, ConfigValue] | None,
        team_ids: Iterable[int] | None = None,
    ) -> IntegrationQuerySet:
        rows = self._rows_of_teams(team_id, team_ids).filter(_where_q(where))
        return rows if external_id is None else rows.filter(integration_id=external_id)

    def with_source_rows(self) -> "IntegrationReader":
        """A reader of the same scope that also sees warehouse source rows.

        Use it only for code that handles every row the same way, such as the integrations list and
        delete API. Code that reads the config of a kind must not see source rows: their config has the
        shape of the warehouse source, not of the kind.
        """
        if self._source_rows == SourceRows.ONLY:
            raise ValueError("This accessor reads only warehouse source rows")
        return IntegrationReader(kinds=self._kinds, auth_type=self._auth_type, source_rows=SourceRows.INCLUDE)

    def _row(self, team_id: int, id: int, *, lock: bool = False) -> Integration:
        rows = self._team_rows(team_id)
        try:
            return (rows.select_for_update() if lock else rows).get(id=id)
        except (Integration.DoesNotExist, ValueError, TypeError) as error:
            raise IntegrationNotFound(f"No integration {id!r} in {self!r} for team {team_id}") from error

    @instrumented("get")
    def get(self, team_id: int, id: int) -> IntegrationRecord:
        """The row with this id. Raises `IntegrationNotFound` when the row is not in the scope."""
        return self._row(team_id, id)

    @instrumented("get_many", rows="returned")
    def get_many(self, team_id: int, ids: Iterable[int]) -> dict[int, IntegrationRecord]:
        """The rows with these ids, keyed by id. Ids that are not in the scope are missing from the result."""
        return {row.id: row for row in self._team_rows(team_id).filter(id__in=list(ids))}

    @instrumented("find")
    def find(
        self,
        team_id: int | None = None,
        *,
        team_ids: Iterable[int] | None = None,
        external_id: str | None = None,
        where: Mapping[str, ConfigValue] | None = None,
    ) -> IntegrationRecord | None:
        """The oldest row with this external id and these config values, or None.

        Pass `team_id` or `team_ids`, not both. An empty `team_ids` finds nothing.
        """
        return self._matching(team_id, external_id, where, team_ids).order_by("created_at", "id").first()

    @instrumented("list", rows="returned")
    def list(
        self,
        team_id: int,
        *,
        external_id: str | None = None,
        where: Mapping[str, ConfigValue] | None = None,
        newest_first: bool = False,
    ) -> builtins.list[IntegrationRecord]:
        order = ("-created_at", "-id") if newest_first else ("created_at", "id")
        return list(self._matching(team_id, external_id, where).order_by(*order))

    @instrumented("exists")
    def exists(
        self,
        team_id: int | None = None,
        *,
        team_ids: Iterable[int] | None = None,
        external_id: str | None = None,
        where: Mapping[str, ConfigValue] | None = None,
    ) -> bool:
        """Pass `team_id` or `team_ids`, not both. An empty `team_ids` is False."""
        return self._matching(team_id, external_id, where, team_ids).exists()

    @instrumented("list_by_external_id", rows="returned")
    def list_by_external_id(
        self, external_id: str, *, team_ids: Iterable[int] | None = None
    ) -> builtins.list[IntegrationRecord]:
        """Rows of every team with this external id, for example the teams that share one GitHub installation.

        Raises `ValueError` on `IntegrationManager.any`, because the result would mix providers.
        """
        rows = self._cross_team_rows("list_by_external_id").filter(integration_id=external_id)
        if team_ids is not None:
            rows = rows.filter(team_id__in=list(team_ids))
        return list(rows.order_by("created_at", "id"))

    @instrumented("get_by_external_id")
    def get_by_external_id(self, external_id: str, id: int) -> IntegrationRecord:
        """The row with this id and this external id, in any team.

        For a callback that names both, such as a GitHub installation and one of its rows. Raises
        `IntegrationNotFound` when the row has another external id or is not in the scope.
        """
        rows = self._cross_team_rows("get_by_external_id")
        try:
            return rows.get(integration_id=external_id, id=id)
        except (Integration.DoesNotExist, ValueError, TypeError) as error:
            raise IntegrationNotFound(f"No integration {id!r} with external id {external_id!r} in {self!r}") from error

    @instrumented("count_by_external_id")
    def count_by_external_id(self, external_id: str) -> int:
        """The number of rows of every team with this external id."""
        return self._cross_team_rows("count_by_external_id").filter(integration_id=external_id).count()

    @instrumented("exists_by_external_id")
    def exists_by_external_id(self, external_id: str) -> bool:
        """True when a row of any team has this external id."""
        return self._cross_team_rows("exists_by_external_id").filter(integration_id=external_id).exists()

    @instrumented("usages")
    def usages(self, team_id: int, id: int) -> builtins.list[IntegrationUsage]:
        """The PostHog objects of the team that use the row. See `usages.py`."""
        row = self._row(team_id, id)
        return integration_usages(team_id, row.id)

    @instrumented("delete")
    def delete(self, team_id: int, id: int, *, ignore_usages: bool = False) -> None:
        """Delete the row. Raises `IntegrationInUse` when other objects use it, unless `ignore_usages`."""
        row = self._row(team_id, id)
        if not ignore_usages:
            usages = integration_usages(team_id, row.id)
            if usages:
                raise IntegrationInUse(usages)
        row.delete()

    @instrumented("delete_by_external_id", rows="written")
    def delete_by_external_id(self, external_id: str) -> int:
        """Delete the rows of every team with this external id, for example after an app is uninstalled.

        Raises `ValueError` on `IntegrationManager.any`, because it would delete rows of other providers.
        All the deletes commit together or not at all. Each row is deleted on its own, so the delete
        signals fire.
        """
        deleted = 0
        with transaction.atomic():
            for row in self._cross_team_rows("delete_by_external_id").filter(integration_id=external_id):
                row.delete()
                deleted += 1
        return deleted

    async def aget(self, team_id: int, id: int) -> IntegrationRecord:
        return await database_sync_to_async(self.get)(team_id, id)

    async def aget_many(self, team_id: int, ids: Iterable[int]) -> dict[int, IntegrationRecord]:
        return await database_sync_to_async(self.get_many)(team_id, list(ids))

    async def afind(
        self,
        team_id: int | None = None,
        *,
        team_ids: Iterable[int] | None = None,
        external_id: str | None = None,
        where: Mapping[str, ConfigValue] | None = None,
    ) -> IntegrationRecord | None:
        return await database_sync_to_async(self.find)(
            team_id, team_ids=None if team_ids is None else list(team_ids), external_id=external_id, where=where
        )

    async def alist(
        self,
        team_id: int,
        *,
        external_id: str | None = None,
        where: Mapping[str, ConfigValue] | None = None,
        newest_first: bool = False,
    ) -> builtins.list[IntegrationRecord]:
        return await database_sync_to_async(self.list)(
            team_id, external_id=external_id, where=where, newest_first=newest_first
        )

    async def aexists(
        self,
        team_id: int | None = None,
        *,
        team_ids: Iterable[int] | None = None,
        external_id: str | None = None,
        where: Mapping[str, ConfigValue] | None = None,
    ) -> bool:
        return await database_sync_to_async(self.exists)(
            team_id, team_ids=None if team_ids is None else list(team_ids), external_id=external_id, where=where
        )

    async def ausages(self, team_id: int, id: int) -> builtins.list[IntegrationUsage]:
        return await database_sync_to_async(self.usages)(team_id, id)

    async def adelete(self, team_id: int, id: int, *, ignore_usages: bool = False) -> None:
        await database_sync_to_async(self.delete)(team_id, id, ignore_usages=ignore_usages)


class AuthAccessor(IntegrationReader):
    """Reads, deletes and writes of the rows of one kind with one auth type."""

    def __init__(self, *, kind: str, auth_type: AuthType, source_rows: SourceRows = SourceRows.EXCLUDE) -> None:
        if source_rows == SourceRows.INCLUDE:
            raise ValueError("A write accessor writes either named rows or warehouse source rows")
        super().__init__(kinds=frozenset({kind}), auth_type=auth_type, source_rows=source_rows)
        self._kind = kind
        self._write_auth_type = auth_type

    def _config_for_write(self, config: Mapping[str, object]) -> dict[str, object]:
        if self._write_auth_type not in kind_auth_types(self._kind).supported:
            raise UnsupportedAuthType(f"Integration kind {self._kind!r} does not support {self._write_auth_type}")
        if AUTH_TYPE_CONFIG_KEY in config:
            raise ValueError("The integrations SDK writes the auth type itself")
        has_marker = SOURCE_MARKER_CONFIG_KEY in config
        if self._source_rows == SourceRows.ONLY and not has_marker:
            raise ValueError(f"A warehouse source row needs config[{SOURCE_MARKER_CONFIG_KEY!r}]")
        if self._source_rows == SourceRows.EXCLUDE and has_marker:
            raise ValueError("Write warehouse source rows through IntegrationManager.source(kind)")
        result = dict(config)
        if self._write_auth_type != default_auth_type(self._kind):
            result[AUTH_TYPE_CONFIG_KEY] = self._write_auth_type.value
        return result

    def _in_scope(self, row: Integration) -> bool:
        return self._team_rows(row.team_id).filter(id=row.id).exists()

    @instrumented("create")
    def create(
        self,
        team_id: int,
        *,
        external_id: str | None,
        config: Mapping[str, object],
        sensitive_config: Mapping[str, object] | None = None,
        created_by_id: int | None = None,
    ) -> IntegrationRecord:
        """Create a row. The SDK writes `config["auth_type"]` when the auth type is not the kind's default.

        Raises `IntegrationConflict` when the team already has a row of the kind with this external id.
        """
        new_config = self._config_for_write(config)
        try:
            with transaction.atomic():
                return _rows().create(
                    team_id=team_id,
                    kind=self._kind,
                    integration_id=external_id,
                    config=new_config,
                    sensitive_config=dict(sensitive_config or {}),
                    created_by_id=created_by_id,
                )
        except IntegrityError as error:
            if not _is_unique_key_violation(error):
                raise
            raise IntegrationConflict(
                f"Team {team_id} already has a {self._kind!r} integration with external id {external_id!r}"
            ) from error

    @instrumented("upsert")
    def upsert(
        self,
        team_id: int,
        external_id: str,
        *,
        config: Mapping[str, object],
        sensitive_config: Mapping[str, object] | None = None,
        created_by_id: int | None = None,
    ) -> tuple[IntegrationRecord, bool]:
        """Create the row with this external id, or replace the config of the existing one.

        Returns the row and True when it is new. Raises `IntegrationConflict` when a row with this
        external id exists outside the scope, for example with another auth type.
        """
        new_config = self._config_for_write(config)
        new_sensitive_config = dict(sensitive_config or {})
        key = {"team_id": team_id, "kind": self._kind, "integration_id": external_id}
        with transaction.atomic():
            row = _rows().select_for_update().filter(**key).first()
            if row is None:
                try:
                    with transaction.atomic():
                        created = _rows().create(
                            **key, config=new_config, sensitive_config=new_sensitive_config, created_by_id=created_by_id
                        )
                    return created, True
                except IntegrityError as error:
                    if not _is_unique_key_violation(error):
                        raise
                    row = _rows().select_for_update().get(**key)
            if not self._in_scope(row):
                raise IntegrationConflict(f"Integration {row.id} with external id {external_id!r} is not in {self!r}")
            row.config = new_config
            row.sensitive_config = new_sensitive_config
            update_fields = ["config", "sensitive_config"]
            if created_by_id is not None:
                row.created_by_id = created_by_id
                update_fields.append("created_by")
            row.save(update_fields=update_fields)
            return row, False

    @instrumented("update")
    def update(
        self,
        team_id: int,
        id: int,
        *,
        config_patch: Mapping[str, object] | None = None,
        config_remove: Iterable[str] = (),
        sensitive_config_patch: Mapping[str, object] | None = None,
        sensitive_config_remove: Iterable[str] = (),
        errors: str | None = None,
    ) -> IntegrationRecord:
        """Merge `config_patch` into the config and drop the keys in `config_remove`. `errors=None` keeps the errors."""
        patch = IntegrationPatch(
            config_patch=dict(config_patch or {}),
            config_remove=tuple(config_remove),
            sensitive_config_patch=dict(sensitive_config_patch or {}),
            sensitive_config_remove=tuple(sensitive_config_remove),
            errors=errors,
        )
        _checked_config_keys([*patch.config_patch, *patch.config_remove])
        with transaction.atomic():
            row = self._row(team_id, id, lock=True)
            update_fields = _patch_row(row, patch)
            if update_fields:
                row.save(update_fields=update_fields)
            return row

    @instrumented("update_by_external_id", rows="written")
    def update_by_external_id(self, external_id: str, patch: IntegrationPatch) -> int:
        """Apply `patch` to the rows of every team with this external id. Returns the number of rows that changed.

        One `bulk_update` writes the changed rows, so no `post_save` signal fires. Rows that the patch
        does not change are not written.
        """
        _checked_config_keys([*patch.config_patch, *patch.config_remove])
        with transaction.atomic():
            rows = (
                self._cross_team_rows("update_by_external_id")
                .select_for_update()
                .filter(integration_id=external_id)
                .order_by("id")
            )
            changed: builtins.list[Integration] = []
            fields: set[str] = set()
            for row in rows:
                row_fields = _patch_row(row, patch)
                if row_fields:
                    changed.append(row)
                    fields.update(row_fields)
            if changed:
                _rows().bulk_update(changed, sorted(fields))
        return len(changed)

    async def acreate(
        self,
        team_id: int,
        *,
        external_id: str | None,
        config: Mapping[str, object],
        sensitive_config: Mapping[str, object] | None = None,
        created_by_id: int | None = None,
    ) -> IntegrationRecord:
        return await database_sync_to_async(self.create)(
            team_id,
            external_id=external_id,
            config=config,
            sensitive_config=sensitive_config,
            created_by_id=created_by_id,
        )

    async def aupsert(
        self,
        team_id: int,
        external_id: str,
        *,
        config: Mapping[str, object],
        sensitive_config: Mapping[str, object] | None = None,
        created_by_id: int | None = None,
    ) -> tuple[IntegrationRecord, bool]:
        return await database_sync_to_async(self.upsert)(
            team_id, external_id, config=config, sensitive_config=sensitive_config, created_by_id=created_by_id
        )

    async def aupdate(
        self,
        team_id: int,
        id: int,
        *,
        config_patch: Mapping[str, object] | None = None,
        config_remove: Iterable[str] = (),
        sensitive_config_patch: Mapping[str, object] | None = None,
        sensitive_config_remove: Iterable[str] = (),
        errors: str | None = None,
    ) -> IntegrationRecord:
        return await database_sync_to_async(self.update)(
            team_id,
            id,
            config_patch=config_patch,
            config_remove=tuple(config_remove),
            sensitive_config_patch=sensitive_config_patch,
            sensitive_config_remove=tuple(sensitive_config_remove),
            errors=errors,
        )


def _same_json(a: object, b: object) -> bool:
    # Python equality treats `1`, `1.0` and `True` as equal, but JSON stores them as different values.
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _patch_row(row: Integration, patch: IntegrationPatch) -> list[str]:
    """Apply `patch` to the row in memory. Returns the fields whose value changed."""
    changed: list[str] = []
    config = _patched(row.config, patch.config_patch, patch.config_remove)
    if not _same_json(config, row.config or {}):
        row.config = config
        changed.append("config")
    sensitive_config = _patched(row.sensitive_config, patch.sensitive_config_patch, patch.sensitive_config_remove)
    if not _same_json(sensitive_config, row.sensitive_config or {}):
        row.sensitive_config = sensitive_config
        changed.append("sensitive_config")
    if patch.errors is not None and patch.errors != row.errors:
        row.errors = patch.errors
        changed.append("errors")
    return changed


class OAuthAccessor(AuthAccessor):
    """Reads and writes of the OAuth rows of one kind, and the refresh of their access tokens."""

    def __init__(self, *, kind: str, source_rows: SourceRows = SourceRows.EXCLUDE) -> None:
        super().__init__(kind=kind, auth_type=AuthType.OAUTH, source_rows=source_rows)

    @instrumented("refresh_access_token")
    def refresh_access_token(
        self, team_id: int, id: int, *, stale_access_token: str | None = None
    ) -> IntegrationRecord:
        """Refresh the access token of the row when it expires soon, and return the row.

        The refresh holds a lock on the row. Some providers rotate the refresh token on each refresh
        and revoke the grant when a token is spent twice, so two workers must not refresh one row at
        the same time. The second worker waits for the lock, and then gets the token that the first
        worker stored.

        Pass `stale_access_token` to refresh also when that token is still the stored access token,
        for example after the provider refused it. When the row has another token, the row comes back
        without a refresh. A refresh that fails does not raise: the row comes back with `errors` set.
        Raises `ValueError` when the kind has no OAuth token refresh.
        """
        if self._kind not in OauthIntegration.supported_kinds:
            raise ValueError(f"Integration kind {self._kind!r} has no OAuth token refresh")
        with transaction.atomic():
            row = self._row(team_id, id, lock=True)
            oauth = OauthIntegration(row)
            stale = stale_access_token is not None and row.access_token == stale_access_token
            if not (stale or oauth.access_token_expired()):
                record_token_refresh(self._kind, "fresh")
                return row
            try:
                oauth.refresh_access_token()
            except Exception:
                record_token_refresh(self._kind, "error")
                raise
            record_token_refresh(self._kind, "error" if row.errors else "stale_token" if stale else "refreshed")
            return row

    async def arefresh_access_token(
        self, team_id: int, id: int, *, stale_access_token: str | None = None
    ) -> IntegrationRecord:
        # Not thread-sensitive: the provider call can be slow, and it must not hold the shared thread
        # that every other sync database call of this event loop waits for. The row lock still applies.
        return await database_sync_to_async(self.refresh_access_token, thread_sensitive=False)(
            team_id, id, stale_access_token=stale_access_token
        )


class KindAccessor:
    """The base of the generated accessor of one kind. Each subclass has one attribute per supported auth type."""

    kind: ClassVar[str]
    any: IntegrationReader


class SourceKindAccessor:
    """The rows of one warehouse source kind. Only rows with `config["warehouse_source_type"]` are in scope."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.oauth = AuthAccessor(kind=kind, auth_type=AuthType.OAUTH, source_rows=SourceRows.ONLY)
        self.token = AuthAccessor(kind=kind, auth_type=AuthType.TOKEN, source_rows=SourceRows.ONLY)
        self.credentials = AuthAccessor(kind=kind, auth_type=AuthType.CREDENTIALS, source_rows=SourceRows.ONLY)
        self.any = IntegrationReader(kinds=frozenset({kind}), source_rows=SourceRows.ONLY)


class IntegrationManagerBase:
    """The hand-written part of `IntegrationManager`. The generated subclass adds one attribute per kind."""

    # Every row of every kind and every auth type, without warehouse source rows. For reads by id with a
    # kind that the caller does not know. `IntegrationManager.any.with_source_rows()` adds the source rows.
    any = IntegrationReader(kinds=None)

    def source(self, kind: str) -> SourceKindAccessor:
        """The warehouse source rows of a registered source kind. Raises `UnknownIntegrationKind`."""
        if not is_source_kind(kind):
            raise UnknownIntegrationKind(f"No warehouse source registered the integration kind {kind!r}")
        return SourceKindAccessor(kind)

    def kinds(
        self, *kinds: str, auth_types: Iterable[AuthType] | Literal["any", "default"] = "default"
    ) -> IntegrationReader:
        """Reads of the named rows of several catalogue kinds.

        By default it reads the default auth type of each kind, because code that names kinds expects
        their usual config shape. `auth_types="any"` reads every auth type. A list reads those auth types.
        """
        unknown = sorted(set(kinds) - set(KINDS))
        if not kinds or unknown:
            raise UnknownIntegrationKind(f"Unknown integration kinds: {unknown or 'none given'}")
        if auth_types == "any":
            return IntegrationReader(kinds=frozenset(kinds))
        if auth_types == "default":
            return IntegrationReader(kinds=frozenset(kinds), auth_type="default")
        return IntegrationReader(kinds=frozenset(kinds), auth_type=frozenset(AuthType(t) for t in auth_types))
