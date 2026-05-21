import json
from typing import Any, Optional, cast
from urllib.parse import urlparse

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.cloud_utils import is_cloud
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.mixins import _is_host_safe
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import CustomSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField, IncrementalFieldType

REQUIRED_TOP_LEVEL_KEYS = ("client", "resources")
ALLOWED_AUTH_TYPES = frozenset({"bearer", "api_key", "http_basic"})
# A sync only ever fetches data. GET covers most APIs; POST covers search/query
# endpoints that take a body. Write verbs (PUT/PATCH/DELETE) are intentionally
# excluded so a misconfigured manifest can't mutate or delete upstream data.
ALLOWED_HTTP_METHODS = frozenset({"GET", "POST"})
# Credential keys that must NOT appear inline in the manifest — they belong in
# the dedicated secret `auth_*` config fields so the API layer can redact them.
INLINE_SECRET_KEYS = ("token", "api_key", "password")


class ManifestValidationError(ValueError):
    """Raised when the user-provided manifest doesn't conform to RESTAPIConfig."""


def validate_manifest(manifest: Any) -> None:
    """Validate the shape of a user-provided REST API manifest.

    Only checks structural correctness — the safety of any URLs in the
    manifest is checked separately by :func:`validate_manifest_urls`, which
    needs the team_id for cloud-vs-self-hosted handling.
    """
    if not isinstance(manifest, dict):
        raise ManifestValidationError("Manifest must be a JSON object")

    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in manifest]
    if missing:
        raise ManifestValidationError(f"Manifest is missing required keys: {', '.join(missing)}")

    client = manifest["client"]
    if not isinstance(client, dict):
        raise ManifestValidationError("'client' must be an object")

    base_url = client.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ManifestValidationError("'client.base_url' must be a non-empty string")

    auth = client.get("auth")
    if auth is not None:
        if not isinstance(auth, dict):
            raise ManifestValidationError("'client.auth' must be an object")
        auth_type = auth.get("type")
        if auth_type not in ALLOWED_AUTH_TYPES:
            raise ManifestValidationError(
                f"'client.auth.type' must be one of {sorted(ALLOWED_AUTH_TYPES)} (got {auth_type!r})"
            )
        inline_secrets = [key for key in INLINE_SECRET_KEYS if auth.get(key)]
        if inline_secrets:
            raise ManifestValidationError(
                f"Credentials must not be embedded in the manifest ({', '.join(inline_secrets)}) — "
                "provide them in the dedicated auth fields instead."
            )

    resources = manifest["resources"]
    if not isinstance(resources, list) or not resources:
        raise ManifestValidationError("'resources' must be a non-empty list")

    seen_names: set[str] = set()
    for index, resource in enumerate(resources):
        if not isinstance(resource, dict):
            raise ManifestValidationError(f"Resource at index {index} must be an object")

        name = resource.get("name")
        if not isinstance(name, str) or not name:
            raise ManifestValidationError(f"Resource at index {index} is missing a 'name'")
        if name in seen_names:
            raise ManifestValidationError(f"Duplicate resource name: {name!r}")
        seen_names.add(name)

        endpoint = resource.get("endpoint")
        if not isinstance(endpoint, dict):
            raise ManifestValidationError(f"Resource {name!r} is missing an 'endpoint' object")

        path = endpoint.get("path")
        if not isinstance(path, str) or not path:
            raise ManifestValidationError(f"Resource {name!r} is missing 'endpoint.path'")

        method = endpoint.get("method")
        if method is not None:
            method_upper = method.upper() if isinstance(method, str) else None
            if method_upper not in ALLOWED_HTTP_METHODS:
                raise ManifestValidationError(
                    f"Resource {name!r}: 'endpoint.method' must be one of {sorted(ALLOWED_HTTP_METHODS)}"
                )


def validate_manifest_urls(manifest: dict[str, Any], team_id: int) -> tuple[bool, str | None]:
    """Walk every URL field in the manifest and reject internal/private hosts.

    Also enforces ``https://`` on PostHog Cloud. Self-hosted instances skip
    the host check via :func:`_is_host_safe` (which is itself a no-op
    outside of cloud).
    """
    base_url = manifest["client"]["base_url"]
    ok, err = _check_url(base_url, team_id)
    if not ok:
        return False, f"Invalid base_url: {err}"

    for resource in manifest["resources"]:
        path = resource.get("endpoint", {}).get("path", "")
        if path.startswith(("http://", "https://")):
            ok, err = _check_url(path, team_id)
            if not ok:
                return False, f"Resource {resource['name']!r}: {err}"

    return True, None


def _check_url(url: str, team_id: int) -> tuple[bool, str | None]:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False, f"URL {url!r} is missing a hostname"
    if is_cloud() and parsed.scheme != "https":
        return False, f"URL {url!r} must use https:// on PostHog Cloud"
    return _is_host_safe(parsed.hostname, team_id)


@SourceRegistry.register
class CustomSource(SimpleSource[CustomSourceConfig]):
    """User-defined REST API source.

    The manifest is a JSON ``RESTAPIConfig`` (same shape as the dict-based
    configs that power Intercom, Attio, Chargebee, etc.) so the existing REST
    engine in ``common/rest_source`` handles pagination, auth, JSONPath
    extraction, and incremental params with no per-source code.

    Auth credentials are stored in separate ``auth_*`` fields, not inline in
    the manifest. ``manifest_json`` holds only the non-secret structure, so the
    generic API machinery redacts the credentials from responses and carries
    them across updates with no source-specific serializer code. The full
    config is rejoined in :meth:`_assemble_manifest` before it reaches the
    REST engine.
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
                        placeholder="",
                        secret=False,
                    ),
                    # One of the three is used per sync, selected by the manifest's
                    # client.auth.type. All secret so the generic API layer redacts them.
                    SourceFieldInputConfig(
                        name="auth_token",
                        label="Bearer token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="auth_api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="auth_password",
                        label="Auth password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "The upstream API rejected the request with HTTP 401. Check that the configured auth credentials are correct.",
            "403 Client Error": "The upstream API rejected the request with HTTP 403. The configured credentials may lack the required permissions.",
        }

    def _assemble_manifest(self, config: CustomSourceConfig) -> RESTAPIConfig:
        """Parse the stored manifest and rejoin it with the auth credentials.

        ``manifest_json`` holds the RESTAPIConfig structure with no credential
        values; the secrets live in separate ``auth_*`` fields so the generic
        API layer can redact them. This rebuilds the full config the REST
        engine consumes.
        """
        try:
            manifest = json.loads(config.manifest_json)
        except json.JSONDecodeError as exc:
            raise ManifestValidationError(f"Manifest is not valid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})")
        validate_manifest(manifest)
        _inject_auth_secrets(manifest, config)
        return cast(RESTAPIConfig, manifest)

    def validate_credentials(
        self, config: CustomSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            manifest = self._assemble_manifest(config)
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
        manifest = self._assemble_manifest(config)

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
        manifest = self._assemble_manifest(config)
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


def _inject_auth_secrets(manifest: dict[str, Any], config: CustomSourceConfig) -> None:
    """Inject credential values from the secret config fields into ``client.auth``.

    Mutates ``manifest`` in place. Which field is used is selected by the
    manifest's declared ``client.auth.type``; an absent/empty value is left
    alone so the upstream probe surfaces the missing-credential error.
    """
    client = manifest.get("client")
    if not isinstance(client, dict):
        return
    auth = client.get("auth")
    if not isinstance(auth, dict):
        return

    auth_type = auth.get("type")
    if auth_type == "bearer" and config.auth_token:
        auth["token"] = config.auth_token
    elif auth_type == "api_key" and config.auth_api_key:
        auth["api_key"] = config.auth_api_key
    elif auth_type == "http_basic" and config.auth_password:
        auth["password"] = config.auth_password


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
