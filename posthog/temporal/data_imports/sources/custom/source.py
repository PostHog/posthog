import json
from typing import Any, Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.custom.manifest_validators import (
    ManifestValidationError,
    validate_manifest,
    validate_manifest_urls,
)
from posthog.temporal.data_imports.sources.generated_configs import CustomSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField, IncrementalFieldType

_MANIFEST_PLACEHOLDER = """{
  "client": {
    "base_url": "https://api.example.com",
    "auth": { "type": "bearer", "token": "<your token>" }
  },
  "resources": [
    {
      "name": "users",
      "primary_key": "id",
      "endpoint": {
        "path": "/v1/users",
        "data_selector": "data",
        "paginator": { "type": "json_response", "next_url_path": "links.next" }
      }
    }
  ]
}"""


@SourceRegistry.register
class CustomSource(SimpleSource[CustomSourceConfig]):
    """User-defined REST API source.

    The manifest is a JSON ``RESTAPIConfig`` (same shape as the dict-based
    configs that power Intercom, Attio, Chargebee, etc.) so the existing
    REST engine in ``common/rest_source`` handles pagination, auth, JSONPath
    extraction, and incremental params with no per-source code.
    """

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CUSTOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CUSTOM,
            label="Custom REST source",
            caption=(
                "Define a REST API source by providing a manifest. "
                "The manifest follows the same shape as PostHog's built-in REST sources — see the docs for the field reference."
            ),
            iconPath="/static/posthog-icon.svg",
            docsUrl=None,
            featureFlag="dwh_custom_source",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="manifest_json",
                        label="Manifest (JSON)",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder=_MANIFEST_PLACEHOLDER,
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "The upstream API rejected the request with HTTP 401. Check that the manifest's auth credentials are correct.",
            "403 Client Error": "The upstream API rejected the request with HTTP 403. The configured credentials may lack the required permissions.",
        }

    def _parse_manifest(self, config: CustomSourceConfig) -> RESTAPIConfig:
        try:
            manifest = json.loads(config.manifest_json)
        except json.JSONDecodeError as exc:
            raise ManifestValidationError(f"Manifest is not valid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})")
        validate_manifest(manifest)
        return cast(RESTAPIConfig, manifest)

    def validate_credentials(
        self, config: CustomSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            manifest = self._parse_manifest(config)
        except ManifestValidationError as exc:
            return False, str(exc)

        ok, err = validate_manifest_urls(dict(manifest), team_id)
        if not ok:
            return False, err

        # Probe the first resource so we surface auth/connection errors at create-time
        # rather than waiting for the first sync. Failure to reach the upstream is treated
        # as a credential failure with the underlying error message returned to the user.
        first = manifest["resources"][0]
        endpoint = first.get("endpoint", {})
        method = (endpoint.get("method") or "GET").upper()
        path = endpoint.get("path", "")
        url = (
            path
            if path.startswith(("http://", "https://"))
            else f"{manifest['client']['base_url'].rstrip('/')}/{path.lstrip('/')}"
        )

        headers: dict[str, str] = dict(manifest["client"].get("headers") or {})
        auth: dict[str, Any] = dict(manifest["client"].get("auth") or {})
        auth_type = auth.get("type")
        if auth_type == "bearer" and auth.get("token"):
            headers.setdefault("Authorization", f"Bearer {auth['token']}")
        elif auth_type == "api_key" and auth.get("api_key"):
            if (auth.get("location") or "header") == "header":
                headers[auth.get("name") or "Authorization"] = auth["api_key"]

        session = make_tracked_session(headers=headers)
        try:
            basic_auth: tuple[str, str] | None = None
            if auth_type == "http_basic":
                basic_auth = (str(auth.get("username", "")), str(auth.get("password", "")))
            response = session.request(method, url, auth=basic_auth, timeout=15)
        except Exception as exc:
            return False, f"Could not reach {url}: {exc}"

        if response.status_code >= 400:
            return False, f"HTTP {response.status_code} from {url}: {response.text[:200]}"
        return True, None

    def get_schemas(
        self,
        config: CustomSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        manifest = self._parse_manifest(config)

        ok, err = validate_manifest_urls(dict(manifest), team_id)
        if not ok:
            raise ManifestValidationError(err or "Manifest URL validation failed")

        schemas: list[SourceSchema] = []
        for resource in manifest["resources"]:
            assert isinstance(resource, dict)
            schemas.append(_schema_from_resource(resource))

        if names is not None:
            wanted = set(names)
            schemas = [schema for schema in schemas if schema.name in wanted]
        return schemas

    def source_for_pipeline(self, config: CustomSourceConfig, inputs: SourceInputs) -> SourceResponse:
        manifest = self._parse_manifest(config)
        ok, err = validate_manifest_urls(dict(manifest), inputs.team_id)
        if not ok:
            raise ManifestValidationError(err or "Manifest URL validation failed")

        chosen = next(
            (r for r in manifest["resources"] if isinstance(r, dict) and r.get("name") == inputs.schema_name),
            None,
        )
        if chosen is None:
            raise ValueError(f"Resource {inputs.schema_name!r} not found in manifest")

        single_resource_manifest = cast(
            RESTAPIConfig,
            {**manifest, "resources": [chosen]},
        )

        resource = rest_api_resource(
            single_resource_manifest,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            db_incremental_field_last_value=(
                inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None
            ),
        )

        primary_key = chosen.get("primary_key")
        primary_keys: list[str] | None
        if isinstance(primary_key, list):
            primary_keys = [str(key) for key in primary_key]
        elif isinstance(primary_key, str):
            primary_keys = [primary_key]
        else:
            primary_keys = None

        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: resource,
            primary_keys=primary_keys,
            partition_count=1,
            partition_size=1,
            partition_mode="md5",
        )


def _schema_from_resource(resource: dict[str, Any]) -> SourceSchema:
    name = resource["name"]
    endpoint = resource.get("endpoint", {})
    incremental_cfg = endpoint.get("incremental") if isinstance(endpoint, dict) else None

    incremental_fields: list[IncrementalField] = []
    if isinstance(incremental_cfg, dict):
        cursor_path = incremental_cfg.get("cursor_path")
        if isinstance(cursor_path, str) and cursor_path:
            incremental_fields = [
                IncrementalField(
                    label=cursor_path,
                    field=cursor_path,
                    type=IncrementalFieldType.DateTime,
                    field_type=IncrementalFieldType.DateTime,
                )
            ]

    primary_key = resource.get("primary_key")
    detected_primary_keys: list[str] | None
    if isinstance(primary_key, list):
        detected_primary_keys = [str(key) for key in primary_key]
    elif isinstance(primary_key, str):
        detected_primary_keys = [primary_key]
    else:
        detected_primary_keys = None

    return SourceSchema(
        name=name,
        supports_incremental=bool(incremental_fields),
        supports_append=False,
        incremental_fields=incremental_fields,
        detected_primary_keys=detected_primary_keys,
    )
