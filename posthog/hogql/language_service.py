from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from time import perf_counter
from typing import Any

from django.conf import settings
from django.db.models import QuerySet

import requests
import posthoganalytics

from posthog.schema import DatabaseSchemaQueryResponse

from posthog.hogql.editor_assist_metrics import (
    LANGUAGE_SERVICE_HTTP_DURATION_SECONDS,
    LANGUAGE_SERVICE_RESPONSE_SIZE_BYTES,
)

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import PropertyDefinition, Team, User
from posthog.taxonomy.property_access import restricted_property_names

from products.event_definitions.backend.models.property_definition import effective_project_id_expr

FEATURE_FLAG = "hogql-language-service"
AFFINITY_HEADER = "X-HogQL-Affinity-Key"


class LanguageServiceError(Exception):
    pass


class CatalogMissing(LanguageServiceError):
    pass


@dataclass(frozen=True)
class LanguageServiceResult:
    body: dict[str, Any]
    duration_seconds: float
    response_size_bytes: int


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


def build_catalog(team: Team, user: User, schema: DatabaseSchemaQueryResponse) -> dict[str, Any]:
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
    return {"tables": tables, "properties": properties}


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
            "POST", team_id, user_id, "autocomplete", "complete", {"query": query, "position": position}, 1
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
            response = requests.request(
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
            body: dict[str, Any] = response.json()
        except requests.JSONDecodeError as error:
            raise LanguageServiceError("language service returned invalid JSON") from error
        return LanguageServiceResult(body=body, duration_seconds=duration, response_size_bytes=len(response.content))
