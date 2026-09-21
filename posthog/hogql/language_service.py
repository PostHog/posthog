from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from hashlib import sha256
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet

import redis
import requests
import structlog
import posthoganalytics

from posthog.schema import DatabaseSchemaDataWarehouseTable, DatabaseSchemaQueryResponse

from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.editor_assist_metrics import (
    LANGUAGE_SERVICE_HTTP_DURATION_SECONDS,
    LANGUAGE_SERVICE_RESPONSE_SIZE_BYTES,
)
from posthog.hogql.errors import QueryError, ResolutionError

from posthog.dataclasses import frozen
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import PropertyDefinition, Team, User
from posthog.redis import get_client
from posthog.security.outbound_proxy import internal_requests
from posthog.taxonomy.property_access import restricted_property_names

from products.event_definitions.backend.models.property_definition import effective_project_id_expr

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

FEATURE_FLAG = "hogql-language-service"
AFFINITY_HEADER = "X-HogQL-Affinity-Key"
WAREHOUSE_ALIAS_CATALOG_REVISION_PREFIX = "warehouse-aliases-v1:"

_CATALOG_PUBLICATION_MARKER_TTL_SECONDS = 5
_CATALOG_PUBLICATION_LOCK_TTL_SECONDS = 10
_CATALOG_PUBLICATION_LOCK_WAIT_SECONDS = 0.25
_CATALOG_PUBLICATION_REDIS_TIMEOUT_SECONDS = 0.1

logger = structlog.get_logger(__name__)


class LanguageServiceError(Exception):
    pass


class CatalogMissing(LanguageServiceError):
    pass


class MalformedLanguageServiceResponse(LanguageServiceError):
    pass


@dataclass(frozen=True)
class LanguageServiceResult:
    body: dict[str, Any]
    duration_seconds: float
    response_size_bytes: int


type CatalogValidationReason = Literal[
    "canonical_not_visible",
    "canonical_unresolvable",
    "canonical_not_warehouse",
    "canonical_id_mismatch",
    "alias_dependency_omitted",
    "alias_not_visible",
    "alias_unresolvable",
    "alias_not_warehouse",
    "alias_ambiguous",
    "alias_canonical_collision",
    "alias_conflict",
]
type _WarehouseResolutionFailure = Literal["not_visible", "unresolvable", "not_warehouse"]

_CANONICAL_FAILURE_REASONS: dict[_WarehouseResolutionFailure, CatalogValidationReason] = {
    "not_visible": "canonical_not_visible",
    "unresolvable": "canonical_unresolvable",
    "not_warehouse": "canonical_not_warehouse",
}
_ALIAS_FAILURE_REASONS: dict[_WarehouseResolutionFailure, CatalogValidationReason] = {
    "not_visible": "alias_not_visible",
    "unresolvable": "alias_unresolvable",
    "not_warehouse": "alias_not_warehouse",
}


@frozen
class CatalogValidationOmission:
    entry_type: Literal["table", "alias"]
    reason: CatalogValidationReason
    table_name: str = field(repr=False)
    alias_name: str | None = field(default=None, repr=False)
    schema_table_id: str | None = field(default=None, repr=False)
    resolver_table_id: str | None = field(default=None, repr=False)


@frozen
class CatalogValidationSummary:
    reasons: tuple[CatalogValidationReason, ...]
    omitted_tables: int
    omitted_aliases: int
    omissions: tuple[CatalogValidationOmission, ...] = field(repr=False)


@frozen
class CatalogBuildResult:
    catalog: dict[str, Any] = field(repr=False)
    validation: CatalogValidationSummary | None


@frozen
class _WarehouseAliasResult:
    aliases: dict[str, str]
    omitted_canonical_names: frozenset[str]
    validation: CatalogValidationSummary | None


def coordinate_catalog_publication(
    team_id: int,
    user_id: int,
    service_target: str,
    check_catalog: Callable[[], LanguageServiceResult | None],
    publish_catalog: Callable[[], None],
) -> LanguageServiceResult | None:
    scope = sha256(
        f"{service_target}:{team_id}:{user_id}:{WAREHOUSE_ALIAS_CATALOG_REVISION_PREFIX}".encode()
    ).hexdigest()
    key_prefix = f"hogql-language-service:catalog-publication:{{{scope}}}"
    marker_key = f"{key_prefix}:success"
    lock_key = f"{key_prefix}:lock"

    try:
        redis_client = get_client(
            socket_timeout=_CATALOG_PUBLICATION_REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=_CATALOG_PUBLICATION_REDIS_TIMEOUT_SECONDS,
        )
        marker_exists = bool(redis_client.get(marker_key))
    except (redis.exceptions.RedisError, ImproperlyConfigured):
        logger.warning("hogql_catalog_publication_redis_unavailable", exc_info=True)
        publish_catalog()
        return check_catalog()

    if marker_exists:
        result = check_catalog()
        if result is not None:
            return result

    try:
        lock = redis_client.lock(
            lock_key,
            timeout=_CATALOG_PUBLICATION_LOCK_TTL_SECONDS,
            blocking_timeout=_CATALOG_PUBLICATION_LOCK_WAIT_SECONDS,
        )
        acquired = lock.acquire()
    except redis.exceptions.RedisError:
        logger.warning("hogql_catalog_publication_lock_unavailable", exc_info=True)
        publish_catalog()
        return check_catalog()

    if not acquired:
        return check_catalog()

    try:
        result = check_catalog()
        if result is not None:
            return result

        publish_catalog()
        try:
            redis_client.set(marker_key, "1", ex=_CATALOG_PUBLICATION_MARKER_TTL_SECONDS)
        except redis.exceptions.RedisError:
            logger.warning("hogql_catalog_publication_marker_failed", exc_info=True)
        return check_catalog()
    finally:
        try:
            lock.release()
        except redis.exceptions.LockNotOwnedError:
            logger.warning("hogql_catalog_publication_lock_expired")
        except redis.exceptions.RedisError:
            logger.warning("hogql_catalog_publication_lock_release_failed", exc_info=True)


def is_language_service_enabled(team: Team, user: User) -> bool:
    if not settings.HOGQL_LANGUAGE_SERVICE_URL or not settings.HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS:
        return False
    if settings.DEBUG:
        return True
    return bool(
        posthoganalytics.feature_enabled(
            FEATURE_FLAG,
            str(user.distinct_id),
            person_properties={"email": user.email},
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


def build_catalog(
    team: Team,
    user: User,
    schema: DatabaseSchemaQueryResponse,
    *,
    database: Database,
) -> CatalogBuildResult:
    warehouse_aliases = _warehouse_table_aliases(schema, database)
    tables: dict[str, Any] = {}
    for name, table in schema.tables.items():
        if name in warehouse_aliases.omitted_canonical_names:
            continue
        fields = {
            field_name: {"name": field.name or field_name, "type": field.type}
            for field_name, field in table.fields.items()
        }
        tables[name] = {"id": table.id, "name": table.name, "type": table.type, "fields": fields}

    properties: dict[str, list[dict[str, str]]] = {}
    for property_type, namespace in (
        (PropertyDefinition.Type.EVENT, "event"),
        (PropertyDefinition.Type.PERSON, "person"),
        (PropertyDefinition.Type.SESSION, "session"),
    ):
        properties[namespace] = _properties_for_namespace(team, user, property_type)
    for group_type_index in range(5):
        properties[f"group:{group_type_index}"] = _properties_for_namespace(
            team, user, PropertyDefinition.Type.GROUP, group_type_index
        )
    return CatalogBuildResult(
        catalog={"tables": tables, "properties": properties, "tableAliases": warehouse_aliases.aliases},
        validation=warehouse_aliases.validation,
    )


def _warehouse_table_aliases(schema: DatabaseSchemaQueryResponse, database: Database) -> _WarehouseAliasResult:
    visible_names = set(database.tables.resolve_visible_table_names())
    canonical_by_resolved_object: dict[int, list[str]] = {}
    valid_warehouse_tables: list[tuple[str, DatabaseSchemaDataWarehouseTable]] = []
    omitted_canonical_names: set[str] = set()
    omitted_alias_names: set[str] = set()
    aliases_from_omitted_tables: dict[str, set[str]] = {}
    failures: set[CatalogValidationReason] = set()
    omissions: set[CatalogValidationOmission] = set()

    for canonical_name, schema_table in schema.tables.items():
        if not isinstance(schema_table, DatabaseSchemaDataWarehouseTable):
            continue
        resolved, failure = _visible_warehouse_table(database, visible_names, canonical_name)
        reason = _CANONICAL_FAILURE_REASONS[failure] if failure is not None else None
        if resolved is not None and resolved.table_id != schema_table.id:
            reason = "canonical_id_mismatch"
        if reason is not None:
            failures.add(reason)
            omitted_canonical_names.add(canonical_name)
            omissions.add(
                CatalogValidationOmission(
                    entry_type="table",
                    reason=reason,
                    table_name=canonical_name,
                    schema_table_id=str(schema_table.id) if reason == "canonical_id_mismatch" else None,
                    resolver_table_id=str(resolved.table_id)
                    if reason == "canonical_id_mismatch" and resolved is not None
                    else None,
                )
            )
            for alias in schema_table.search_aliases or []:
                if alias != canonical_name:
                    aliases_from_omitted_tables.setdefault(alias, set()).add(canonical_name)
            continue
        assert resolved is not None
        valid_warehouse_tables.append((canonical_name, schema_table))
        canonical_by_resolved_object.setdefault(id(resolved), []).append(canonical_name)

    aliases: dict[str, str] = {}
    canonical_names = set(schema.tables)
    for canonical_name, schema_table in valid_warehouse_tables:
        for alias in schema_table.search_aliases or []:
            if alias in omitted_alias_names:
                continue
            resolved, failure = _visible_warehouse_table(database, visible_names, alias)
            if failure is not None:
                reason = _ALIAS_FAILURE_REASONS[failure]
                failures.add(reason)
                omitted_alias_names.add(alias)
                omissions.add(
                    CatalogValidationOmission(
                        entry_type="alias", reason=reason, table_name=canonical_name, alias_name=alias
                    )
                )
                continue
            assert resolved is not None
            targets = canonical_by_resolved_object.get(id(resolved), [])
            if len(targets) != 1:
                failures.add("alias_ambiguous")
                omitted_alias_names.add(alias)
                omissions.add(
                    CatalogValidationOmission(
                        entry_type="alias",
                        reason="alias_ambiguous",
                        table_name=canonical_name,
                        alias_name=alias,
                    )
                )
                continue
            target = targets[0]
            if alias == target:
                continue
            if alias in canonical_names:
                failures.add("alias_canonical_collision")
                omitted_alias_names.add(alias)
                omissions.add(
                    CatalogValidationOmission(
                        entry_type="alias",
                        reason="alias_canonical_collision",
                        table_name=canonical_name,
                        alias_name=alias,
                    )
                )
                continue
            previous = aliases.get(alias)
            if previous is not None and previous != target:
                failures.add("alias_conflict")
                omitted_alias_names.add(alias)
                aliases.pop(alias)
                omissions.add(
                    CatalogValidationOmission(
                        entry_type="alias",
                        reason="alias_conflict",
                        table_name=canonical_name,
                        alias_name=alias,
                    )
                )
                continue
            aliases[alias] = target

    for alias, declaring_tables in aliases_from_omitted_tables.items():
        if alias in aliases or alias in omitted_alias_names:
            continue
        failures.add("alias_dependency_omitted")
        omitted_alias_names.add(alias)
        omissions.update(
            CatalogValidationOmission(
                entry_type="alias",
                reason="alias_dependency_omitted",
                table_name=canonical_name,
                alias_name=alias,
            )
            for canonical_name in declaring_tables
        )

    validation = None
    if failures:
        validation = CatalogValidationSummary(
            reasons=tuple(sorted(failures)),
            omitted_tables=len(omitted_canonical_names),
            omitted_aliases=len(omitted_alias_names),
            omissions=tuple(
                sorted(
                    omissions,
                    key=lambda omission: (
                        omission.entry_type,
                        omission.table_name,
                        omission.alias_name or "",
                        omission.reason,
                    ),
                )
            ),
        )
    return _WarehouseAliasResult(
        aliases=aliases,
        omitted_canonical_names=frozenset(omitted_canonical_names),
        validation=validation,
    )


def _visible_warehouse_table(
    database: Database, visible_names: set[str], name: str
) -> tuple[S3Table | None, _WarehouseResolutionFailure | None]:
    if name not in visible_names:
        return None, "not_visible"
    try:
        table = database.get_table(name)
    except (QueryError, ResolutionError):
        return None, "unresolvable"
    if not isinstance(table, S3Table) or table.table_id is None:
        return None, "not_warehouse"
    return table, None


def _properties_for_namespace(
    team: Team, user: User, property_type: PropertyDefinition.Type, group_type_index: int | None = None
) -> list[dict[str, str]]:
    restricted = restricted_property_names(team, user, property_type)
    queryset: QuerySet[PropertyDefinition] = PropertyDefinition.objects.alias(
        effective_project_id=effective_project_id_expr()
    ).filter(effective_project_id=team.pk, type=property_type)
    if property_type == PropertyDefinition.Type.GROUP:
        queryset = queryset.filter(group_type_index=group_type_index)
    if restricted:
        queryset = queryset.exclude(name__in=restricted)
    return [
        {"name": name, "property_type": value_type or ""}
        for name, value_type in queryset.order_by("name").values_list("name", "property_type")
    ]


class LanguageServiceClient:
    def __init__(self) -> None:
        self.base_url = settings.HOGQL_LANGUAGE_SERVICE_URL.rstrip("/")
        keys: list[str] = settings.HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS
        if not self.base_url or not keys:
            raise LanguageServiceError("HogQL language service is not configured")
        self.signing_key = keys[0]

    def publish(self, team_id: int, user_id: int, revision: str, catalog: dict[str, Any]) -> LanguageServiceResult:
        return self._request(
            "PUT", team_id, user_id, "catalog", "publish", {"revision": revision, "catalog": catalog}, 10
        )

    def autocomplete(self, team_id: int, user_id: int, query: str, position: int) -> LanguageServiceResult:
        return self._request(
            "POST",
            team_id,
            user_id,
            "autocomplete",
            "complete",
            {"query": query, "position": position, "positionEncoding": "utf-16"},
            1,
        )

    def validate(self, team_id: int, user_id: int, query: str) -> LanguageServiceResult:
        return self._request("POST", team_id, user_id, "validate", "validate", {"query": query}, 1)

    def _request(
        self,
        method: str,
        team_id: int,
        user_id: int,
        endpoint: str,
        operation: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> LanguageServiceResult:
        token = encode_jwt(
            {"team_id": team_id, "user_id": user_id, "operations": [operation]},
            timedelta(minutes=1),
            PosthogJwtAudience.HOGQL_LANGUAGE_SERVICE,
            signing_key=self.signing_key,
        )
        started = perf_counter()
        affinity_key = sha256(f"{team_id}:{user_id}".encode()).hexdigest()
        try:
            response = internal_requests.request(
                method,
                f"{self.base_url}/teams/{team_id}/users/{user_id}/{endpoint}",
                json=payload,
                headers={"Authorization": f"Bearer {token}", AFFINITY_HEADER: affinity_key},
                timeout=(0.25, timeout_seconds),
            )
        except requests.RequestException as error:
            raise LanguageServiceError(str(error)) from error
        finally:
            duration = perf_counter() - started
            LANGUAGE_SERVICE_HTTP_DURATION_SECONDS.labels(operation=operation).observe(duration)
        LANGUAGE_SERVICE_RESPONSE_SIZE_BYTES.labels(operation=operation).observe(len(response.content))
        if response.status_code == 404:
            raise CatalogMissing("catalog not found")
        if not response.ok:
            raise LanguageServiceError(f"language service returned {response.status_code}: {response.text[:256]}")
        try:
            body: object = response.json()
        except requests.JSONDecodeError as error:
            raise MalformedLanguageServiceResponse("language service returned invalid JSON") from error
        if not isinstance(body, dict):
            raise MalformedLanguageServiceResponse("language service returned a non-object JSON response")
        return LanguageServiceResult(body=body, duration_seconds=duration, response_size_bytes=len(response.content))
