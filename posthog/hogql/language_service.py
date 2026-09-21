from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from time import perf_counter
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

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


@frozen
class CatalogScope:
    """The catalog one editor-assist request reads and writes.

    A direct warehouse connection exposes its own tables, so its catalog cannot share a slot with
    the team's PostHog catalog, nor with another connection's.
    """

    team_id: int
    user_id: int
    connection_id: str | None = None

    @property
    def path_prefix(self) -> str:
        base = f"teams/{self.team_id}/users/{self.user_id}"
        if self.connection_id is None:
            return base
        return f"{base}/connections/{quote(self.connection_id, safe='')}"

    @property
    def key(self) -> str:
        """Stable identity for affinity routing and the publication lock.

        A scope without a connection keeps the pre-connection spelling, so a deploy does not move
        every warm catalog to a different pod at once.
        """
        if self.connection_id is None:
            return f"{self.team_id}:{self.user_id}"
        return f"{self.team_id}:{self.user_id}:{self.connection_id}"


def coordinate_catalog_publication(
    scope: CatalogScope,
    service_target: str,
    check_catalog: Callable[[], LanguageServiceResult | None],
    publish_catalog: Callable[[], None],
) -> LanguageServiceResult | None:
    scope_hash = sha256(f"{service_target}:{scope.key}:{WAREHOUSE_ALIAS_CATALOG_REVISION_PREFIX}".encode()).hexdigest()
    key_prefix = f"hogql-language-service:catalog-publication:{{{scope_hash}}}"
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
) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for name, table in schema.tables.items():
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
    return {
        "tables": tables,
        "properties": properties,
        "tableAliases": _warehouse_table_aliases(schema, database),
    }


def _warehouse_table_aliases(schema: DatabaseSchemaQueryResponse, database: Database) -> dict[str, str]:
    visible_names = set(database.tables.resolve_visible_table_names())
    canonical_by_resolved_object: dict[int, list[str]] = {}
    warehouse_tables: list[DatabaseSchemaDataWarehouseTable] = []

    for canonical_name, schema_table in schema.tables.items():
        if not isinstance(schema_table, DatabaseSchemaDataWarehouseTable):
            continue
        warehouse_tables.append(schema_table)
        resolved = _visible_warehouse_table(database, visible_names, canonical_name)
        if resolved is None:
            # A direct connection serves the live tables of one external database. They are not
            # S3-backed and carry no alternate name, so they never stand in as an alias target.
            continue
        if resolved.table_id != schema_table.id:
            raise LanguageServiceError(f"catalog table {canonical_name!r} does not match the HogQL resolver")
        canonical_by_resolved_object.setdefault(id(resolved), []).append(canonical_name)

    aliases: dict[str, str] = {}
    canonical_names = set(schema.tables)
    for schema_table in warehouse_tables:
        for alias in schema_table.search_aliases or []:
            resolved = _visible_warehouse_table(database, visible_names, alias)
            targets = canonical_by_resolved_object.get(id(resolved), []) if resolved is not None else []
            if len(targets) != 1:
                raise LanguageServiceError(f"catalog alias {alias!r} has no unique visible target")
            target = targets[0]
            if alias == target:
                continue
            if alias in canonical_names:
                raise LanguageServiceError(f"catalog alias {alias!r} collides with a canonical table")
            previous = aliases.setdefault(alias, target)
            if previous != target:
                raise LanguageServiceError(f"catalog alias {alias!r} resolves to conflicting tables")
    return aliases


def _visible_warehouse_table(database: Database, visible_names: set[str], name: str) -> S3Table | None:
    """The S3 table behind a catalog name, or None when the name resolves to something else."""
    if name not in visible_names:
        raise LanguageServiceError(f"catalog table {name!r} is not visible")
    try:
        table = database.get_table(name)
    except (QueryError, ResolutionError) as error:
        raise LanguageServiceError(f"catalog table {name!r} cannot be resolved") from error
    if not isinstance(table, S3Table) or table.table_id is None:
        return None
    return table


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

    def publish(self, scope: CatalogScope, revision: str, catalog: dict[str, Any]) -> LanguageServiceResult:
        return self._request("PUT", scope, "catalog", "publish", {"revision": revision, "catalog": catalog}, 10)

    def autocomplete(self, scope: CatalogScope, query: str, position: int) -> LanguageServiceResult:
        return self._request(
            "POST",
            scope,
            "autocomplete",
            "complete",
            {"query": query, "position": position, "positionEncoding": "utf-16"},
            1,
        )

    def validate(self, scope: CatalogScope, query: str) -> LanguageServiceResult:
        return self._request("POST", scope, "validate", "validate", {"query": query}, 1)

    def _request(
        self,
        method: str,
        scope: CatalogScope,
        endpoint: str,
        operation: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> LanguageServiceResult:
        claims: dict[str, Any] = {"team_id": scope.team_id, "user_id": scope.user_id, "operations": [operation]}
        if scope.connection_id is not None:
            claims["connection_id"] = scope.connection_id
        token = encode_jwt(
            claims,
            timedelta(minutes=1),
            PosthogJwtAudience.HOGQL_LANGUAGE_SERVICE,
            signing_key=self.signing_key,
        )
        started = perf_counter()
        affinity_key = sha256(scope.key.encode()).hexdigest()
        try:
            response = internal_requests.request(
                method,
                f"{self.base_url}/{scope.path_prefix}/{endpoint}",
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
