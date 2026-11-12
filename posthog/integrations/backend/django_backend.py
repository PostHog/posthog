"""The `StorageBackend` that keeps the rows in the `Integration` Django model.

This is the only module of the SDK that queries the model. The rows come back as model instances,
typed as the read-only `IntegrationRecord`.
"""

import builtins
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import Count, Q

import structlog

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.integrations.backend.patching import changed_fields
from posthog.integrations.backend.protocol import (
    KindScope,
    NewIntegration,
    RowFilter,
    RowScope,
    SourceRows,
    TokenRefresh,
)
from posthog.integrations.contracts import (
    SOURCE_MARKER_CONFIG_KEY,
    ConfigValue,
    CrossTeamFilter,
    IntegrationConflict,
    IntegrationNotFound,
    IntegrationPatch,
    IntegrationRecord,
    RepositoryCache,
    UpdatedRows,
)
from posthog.integrations.enums import AuthType
from posthog.integrations.secret_reads import (
    UndecryptedIntegrationSecretError,
    integration_secret_decrypt_counter,
    looks_encrypted,
)
from posthog.models.integration.auth_types import ANY, default_auth_type
from posthog.models.integration.model import Integration, IntegrationQuerySet, defer_repository_cache_fields
from posthog.models.integration.oauth import OauthIntegration

logger = structlog.get_logger(__name__)

# The unique key of a row: (team, kind, external id).
_UNIQUE_KEY_CONSTRAINT = "posthog_integration_kind_id_unique"


def peel_secret_layers(row: Integration) -> None:
    """Remove the extra encryption layers of the secrets that the row loaded with. `Integration.from_db` calls it.

    `sensitive_config` sets `ignore_decrypt_errors=True`, so a read-then-save of a row whose secret
    failed to decrypt writes that ciphertext back encrypted again, and one decrypt (the field's own)
    then leaves ciphertext behind. The secret under the layers is intact, so remove them here. A value
    that no configured key opens stays as it is, and `readable_secret` refuses to give it out.
    """
    field = cast(EncryptedJSONField, Integration._meta.get_field("sensitive_config"))
    recovered: builtins.list[str] = []

    def peeled(value: object, top_key: str) -> object:
        if isinstance(value, dict):
            return {key: peeled(item, top_key) for key, item in value.items()}
        if isinstance(value, builtins.list):
            return [peeled(item, top_key) for item in value]
        if not looks_encrypted(value):
            return value
        plain = field.decrypt_all_layers(cast(str, value))
        if plain is None:
            return value
        recovered.append(top_key)
        return plain

    sensitive_config = row.sensitive_config
    if not isinstance(sensitive_config, dict):
        return
    cleaned = {key: peeled(value, key) for key, value in sensitive_config.items()}
    if not recovered:
        return
    row.sensitive_config = cleaned
    # A deferred `kind` would cost a query, so read only what the row loaded.
    kind = row.__dict__.get("kind") or "unknown"
    for field_name in sorted(set(recovered)):
        integration_secret_decrypt_counter.labels(kind=kind, result="recovered").inc()
        logger.warning(
            "integration_sensitive_config_over_encrypted",
            integration_id=row.pk,
            team_id=row.__dict__.get("team_id"),
            kind=kind,
            field=field_name,
        )


def _rows() -> IntegrationQuerySet:
    # The GitHub repository cache can be large. Django loads a deferred column when code reads it.
    return defer_repository_cache_fields(Integration.objects._with_auth(ANY))


def _auth_type_q(kind: str, auth_type: AuthType) -> Q:
    stored = Q(config__auth_type=auth_type.value)
    if auth_type == default_auth_type(kind):
        # A JSON null counts as unset, the same as in `auth_types.rows_with_default_auth_type_q`. A
        # stored default is possible too: `QuerySet.update()` skips the `normalized_config` of `save()`.
        return Q(config__auth_type__isnull=True) | Q(config__auth_type=None) | stored
    return stored


def _kind_name(kind: KindScope) -> str:
    return kind.kind


def _scope_q(scope: RowScope) -> Q:
    q = Q()
    if scope.kinds is not None:
        if all(kind.auth_types is None for kind in scope.kinds):
            q &= Q(kind__in=sorted(kind.kind for kind in scope.kinds))
        else:
            # An empty Q() in an OR matches every row, so start from a clause that matches none.
            by_kind = Q(pk__in=[])
            for kind in sorted(scope.kinds, key=_kind_name):
                if kind.auth_types is None:
                    by_kind |= Q(kind=kind.kind)
                    continue
                for auth_type in sorted(kind.auth_types):
                    by_kind |= Q(kind=kind.kind) & _auth_type_q(kind.kind, auth_type)
            q &= by_kind
    if scope.source_rows == SourceRows.EXCLUDE:
        q &= ~Q(config__has_key=SOURCE_MARKER_CONFIG_KEY)
    elif scope.source_rows == SourceRows.ONLY:
        q &= Q(config__has_key=SOURCE_MARKER_CONFIG_KEY)
    return q


def _where_q(where: Mapping[str, ConfigValue]) -> Q:
    q = Q()
    for key, value in where.items():
        # `__exact`, so a key named like a lookup (`contains`, `regex`) still reads as a key.
        # nosemgrep: orm-field-injection - the accessor checks that the key is one JSON key segment, and `__exact` fixes the lookup
        q &= Q(**{f"config__{key}__exact": value})
    return q


def _cross_team_config_q(cross_team_filter: CrossTeamFilter) -> Q:
    # The accessor checks that each key is one JSON key segment, or two for `where_iexact`.
    q = _where_q(cross_team_filter.where)
    for key, values in cross_team_filter.where_in.items():
        # nosemgrep: orm-field-injection - the accessor checks the key, and `__in` fixes the lookup
        q &= Q(**{f"config__{key}__in": builtins.list(values)})
    for path, text in cross_team_filter.where_iexact.items():
        # nosemgrep: orm-field-injection - the accessor checks each key segment, and `__iexact` fixes the lookup
        q &= Q(**{f"config__{path.replace('.', '__')}__iexact": text})
    if cross_team_filter.has_config_key is not None:
        q &= Q(config__has_key=cross_team_filter.has_config_key)
    return q


def _is_unique_key_violation(error: IntegrityError) -> bool:
    constraint = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
    return constraint == _UNIQUE_KEY_CONSTRAINT or _UNIQUE_KEY_CONSTRAINT in str(error)


def _patch_row(row: Integration, patch: IntegrationPatch) -> builtins.list[str]:
    """Apply `patch` to the row in memory. Returns the fields whose value changed."""
    changed = changed_fields(config=row.config, sensitive_config=row.sensitive_config, errors=row.errors, patch=patch)
    for field, value in changed.items():
        setattr(row, field, value)
    return builtins.list(changed)


def _stores_access_token(row: Integration, access_token: str) -> bool:
    try:
        stored = row.access_token
    except UndecryptedIntegrationSecretError:
        # A caller that holds an unreadable token passes the stored value as it is.
        stored = row.sensitive_config.get("access_token")
    return (stored or "") == access_token


class DjangoBackend:
    """The rows in the `posthog_integration` table of the Django database."""

    def _team_rows(self, scope: RowScope, team_id: int) -> IntegrationQuerySet:
        return _rows().filter(_scope_q(scope), team_id=team_id)

    def _selected(self, scope: RowScope, row_filter: RowFilter) -> IntegrationQuerySet:
        if row_filter.team_id is not None:
            rows = self._team_rows(scope, row_filter.team_id)
        elif row_filter.team_ids is not None:
            rows = _rows().filter(_scope_q(scope), team_id__in=builtins.list(row_filter.team_ids))
        else:
            rows = _rows().filter(_scope_q(scope))
        rows = rows.filter(_where_q(row_filter.where))
        return rows if row_filter.external_id is None else rows.filter(integration_id=row_filter.external_id)

    def _row(self, scope: RowScope, team_id: int, id: int, *, lock: bool = False) -> Integration:
        rows = self._team_rows(scope, team_id)
        try:
            return (rows.select_for_update() if lock else rows).get(id=id)
        except (Integration.DoesNotExist, ValueError, TypeError) as error:
            raise IntegrationNotFound(f"No integration {id!r} in {scope!r} for team {team_id}") from error

    def get(self, scope: RowScope, *, team_id: int, id: int) -> IntegrationRecord:
        return self._row(scope, team_id, id)

    def get_many(self, scope: RowScope, *, team_id: int, ids: Sequence[int]) -> dict[int, IntegrationRecord]:
        return {row.id: row for row in self._team_rows(scope, team_id).filter(id__in=builtins.list(ids))}

    def find(self, scope: RowScope, row_filter: RowFilter) -> IntegrationRecord | None:
        return self._selected(scope, row_filter).order_by("created_at", "id").first()

    def list(
        self, scope: RowScope, row_filter: RowFilter, *, newest_first: bool = False
    ) -> builtins.list[IntegrationRecord]:
        order = ("-created_at", "-id") if newest_first else ("created_at", "id")
        return builtins.list(self._selected(scope, row_filter).order_by(*order))

    def exists(self, scope: RowScope, row_filter: RowFilter) -> bool:
        return self._selected(scope, row_filter).exists()

    def count(self, scope: RowScope, row_filter: RowFilter) -> int:
        return self._selected(scope, row_filter).count()

    def count_by_external_ids(self, scope: RowScope, *, external_ids: Sequence[str]) -> dict[str, int]:
        grouped = (
            _rows()
            .filter(_scope_q(scope), integration_id__in=builtins.list(external_ids))
            .order_by()
            .values("integration_id")
            .annotate(count=Count("id"))
        )
        return {str(row["integration_id"]): row["count"] for row in grouped}

    def get_by_external_id(self, scope: RowScope, *, external_id: str, id: int) -> IntegrationRecord:
        try:
            return _rows().filter(_scope_q(scope)).get(integration_id=external_id, id=id)
        except (Integration.DoesNotExist, ValueError, TypeError) as error:
            raise IntegrationNotFound(f"No integration {id!r} with external id {external_id!r} in {scope!r}") from error

    def list_across_teams(
        self, scope: RowScope, cross_team_filter: CrossTeamFilter
    ) -> builtins.list[IntegrationRecord]:
        f = cross_team_filter
        # The scope always names kinds here, so Postgres can use the `(kind, integration_id)` index.
        rows = _rows().filter(_scope_q(scope), _cross_team_config_q(f))
        if f.team_ids is not None:
            rows = rows.filter(team_id__in=builtins.list(f.team_ids))
        if f.exclude_team_ids:
            rows = rows.exclude(team_id__in=builtins.list(f.exclude_team_ids))
        if f.created_by_ids is not None:
            rows = rows.filter(created_by_id__in=builtins.list(f.created_by_ids))
        if f.external_id is not None:
            rows = rows.filter(integration_id=f.external_id)
        if f.after_id is not None:
            rows = rows.filter(id__lt=f.after_id) if f.newest_first else rows.filter(id__gt=f.after_id)
        rows = rows.order_by("-id" if f.newest_first else "id")
        return builtins.list(rows if f.limit is None else rows[: f.limit])

    def create(self, new: NewIntegration) -> IntegrationRecord:
        try:
            with transaction.atomic():
                return _rows().create(
                    team_id=new.team_id,
                    kind=new.kind,
                    integration_id=new.external_id,
                    config=dict(new.config),
                    sensitive_config=dict(new.sensitive_config),
                    created_by_id=new.created_by_id,
                )
        except IntegrityError as error:
            if not _is_unique_key_violation(error):
                raise
            raise IntegrationConflict(
                f"Team {new.team_id} already has a {new.kind!r} integration with external id {new.external_id!r}"
            ) from error

    def upsert(self, scope: RowScope, new: NewIntegration) -> tuple[IntegrationRecord, bool]:
        new_config = dict(new.config)
        new_sensitive_config = dict(new.sensitive_config)
        key = {"team_id": new.team_id, "kind": new.kind, "integration_id": new.external_id}
        with transaction.atomic():
            row = _rows().select_for_update().filter(**key).first()
            if row is None:
                try:
                    with transaction.atomic():
                        created = _rows().create(
                            **key,
                            config=new_config,
                            sensitive_config=new_sensitive_config,
                            created_by_id=new.created_by_id,
                        )
                    return created, True
                except IntegrityError as error:
                    if not _is_unique_key_violation(error):
                        raise
                    row = _rows().select_for_update().get(**key)
            if not self._team_rows(scope, row.team_id).filter(id=row.id).exists():
                raise IntegrationConflict(
                    f"Integration {row.id} with external id {new.external_id!r} is not in {scope!r}"
                )
            row.config = new_config
            row.sensitive_config = new_sensitive_config
            # A new config is a reconnect, so the errors of the old connection go.
            row.errors = ""
            update_fields = ["config", "sensitive_config", "errors"]
            if new.created_by_id is not None:
                row.created_by_id = new.created_by_id
                update_fields.append("created_by")
            row.save(update_fields=update_fields)
            return row, False

    def update(self, scope: RowScope, *, team_id: int, id: int, patch: IntegrationPatch) -> IntegrationRecord:
        with transaction.atomic():
            row = self._row(scope, team_id, id, lock=True)
            update_fields = _patch_row(row, patch)
            if update_fields:
                row.save(update_fields=update_fields)
            return row

    def delete(self, scope: RowScope, *, team_id: int, id: int) -> None:
        self._row(scope, team_id, id).delete()

    def change_external_id(self, scope: RowScope, *, team_id: int, id: int, external_id: str) -> IntegrationRecord:
        with transaction.atomic():
            row = self._row(scope, team_id, id, lock=True)
            if row.integration_id == external_id:
                return row
            row.integration_id = external_id
            try:
                with transaction.atomic():
                    row.save(update_fields=["integration_id"])
            except IntegrityError as error:
                if not _is_unique_key_violation(error):
                    raise
                raise IntegrationConflict(
                    f"Team {team_id} already has a {row.kind!r} integration with external id {external_id!r}"
                ) from error
            return row

    def update_by_external_id(self, scope: RowScope, *, external_id: str, patch: IntegrationPatch) -> int:
        # One `bulk_update` writes the changed rows, so no `post_save` signal fires.
        with transaction.atomic():
            rows = _rows().filter(_scope_q(scope)).select_for_update().filter(integration_id=external_id).order_by("id")
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

    def delete_by_external_id(self, scope: RowScope, *, external_id: str) -> int:
        # Each row is deleted on its own, so the delete signals fire.
        deleted = 0
        with transaction.atomic():
            for row in _rows().filter(_scope_q(scope)).filter(integration_id=external_id):
                row.delete()
                deleted += 1
        return deleted

    def refresh_access_token(
        self, scope: RowScope, *, team_id: int, id: int, stale_access_token: str | None
    ) -> TokenRefresh:
        with transaction.atomic():
            row = self._row(scope, team_id, id, lock=True)
            oauth = OauthIntegration(row)
            stale = stale_access_token is not None and _stores_access_token(row, stale_access_token)
            expired = oauth.access_token_expired()
            if not (stale or expired):
                return TokenRefresh(record=row, result="fresh")
            update_fields = _patch_row(row, oauth.token_refresh_patch())
            if update_fields:
                row.save(update_fields=update_fields)
            return TokenRefresh(record=row, result="error" if row.errors else "refreshed" if expired else "stale_token")

    def update_where(self, scope: RowScope, row_filter: RowFilter, patch: IntegrationPatch) -> UpdatedRows:
        changed: builtins.list[int] = []
        with transaction.atomic():
            # Lock in id order, so two writers of overlapping rows cannot deadlock.
            rows = builtins.list(self._selected(scope, row_filter).select_for_update().order_by("id"))
            for row in rows:
                update_fields = _patch_row(row, patch)
                if update_fields:
                    row.save(update_fields=update_fields)
                    changed.append(row.id)
        rows.sort(key=lambda row: (row.created_at, row.id))
        return UpdatedRows(records=tuple(rows), changed_ids=frozenset(changed))

    def get_repository_cache(self, scope: RowScope, *, team_id: int, id: int) -> RepositoryCache:
        stored = (
            self._team_rows(scope, team_id)
            .filter(id=id)
            .values_list("repository_cache", "repository_cache_updated_at")
            .first()
        )
        if stored is None:
            raise IntegrationNotFound(f"No integration {id!r} in {scope!r} for team {team_id}")
        repositories, updated_at = stored
        return RepositoryCache(repositories=repositories, updated_at=updated_at)

    def set_repository_cache(
        self,
        scope: RowScope,
        *,
        team_id: int,
        id: int,
        repositories: builtins.list[dict[str, object]] | None,
        updated_at: datetime,
    ) -> None:
        # A queryset update writes only the cache columns, so a concurrent write of the config is kept.
        fields: dict[str, Any] = {"repository_cache_updated_at": updated_at}
        if repositories is not None:
            fields["repository_cache"] = repositories
        if not self._team_rows(scope, team_id).filter(id=id).update(**fields):
            raise IntegrationNotFound(f"No integration {id!r} in {scope!r} for team {team_id}")

    def expire_repository_cache_by_external_id(self, scope: RowScope, *, external_id: str) -> int:
        return _rows().filter(_scope_q(scope), integration_id=external_id).update(repository_cache_updated_at=None)
