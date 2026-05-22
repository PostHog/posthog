import json
from typing import Any, Literal, Optional, cast
from urllib.parse import urlparse

from django.conf import settings

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.cloud_utils import is_cloud
from posthog.temporal.data_imports.host_safety import _is_host_safe
from posthog.temporal.data_imports.pipelines.pipeline.typings import SortMode, SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.config_setup import create_auth
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import CustomSourceConfig
from posthog.temporal.data_imports.util import NonRetryableException

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField, IncrementalFieldType

# Credential keys that must NOT appear inline in the manifest — they belong in
# the dedicated secret `auth_*` config fields so the API layer can redact them.
INLINE_SECRET_KEYS = ("token", "api_key", "password")


def is_custom_source_available_for_team(team_id: int | None) -> bool:
    # While the custom source is in development it is restricted to a single
    # pilot team on PostHog Cloud US. The wizard listing is gated client-side by
    # the `dwh_custom_source` feature flag; this is the server-side enforcement
    # that rejects creation from anywhere else (other cloud regions, self-hosted).
    # Temporary: remove this gate once SSRF protection for arbitrary user-supplied
    # URLs is enabled, after which the source can open up to all teams.
    allowed_team_id = 2
    return settings.CLOUD_DEPLOYMENT == "US" and team_id == allowed_team_id


class ManifestValidationError(ValueError):
    """Raised when the user-provided manifest doesn't conform to RESTAPIConfig."""


class _ManifestAuth(BaseModel):
    # Only the non-secret auth fields are modelled, and extras are forbidden:
    # a misspelled key (e.g. `header` instead of `name`) fails manifest
    # validation here with a clear message instead of crashing the REST
    # engine's `create_auth` with an unexpected-kwarg TypeError at sync time.
    model_config = ConfigDict(extra="forbid")

    type: Literal["bearer", "api_key", "http_basic"]
    name: str | None = None
    location: Literal["header", "query", "param", "cookie"] | None = None
    username: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_inline_credentials(cls, data: Any) -> Any:
        # Credentials belong in the secret auth_* config fields, never inline in
        # the manifest — the manifest field is non-secret and round-trips to the client.
        if isinstance(data, dict):
            inline = [key for key in INLINE_SECRET_KEYS if data.get(key)]
            if inline:
                raise ValueError(
                    f"Credentials ({', '.join(inline)}) must not be embedded — use the dedicated auth fields"
                )
        return data


class _ManifestClient(BaseModel):
    base_url: str = Field(min_length=1)
    auth: _ManifestAuth | None = None


class _ManifestEndpoint(BaseModel):
    path: str = Field(min_length=1)
    # GET and POST only. Data-warehouse syncs only ever read upstream data;
    # POST is permitted because some read/query-style endpoints require it, but
    # PUT/PATCH/DELETE are excluded so a misconfigured manifest can't mutate or
    # delete upstream data.
    method: Literal["GET", "POST", "get", "post"] | None = None
    # Query params and request body. Modelled only so a malformed `params`/`json`
    # (e.g. a JSON array where an object is expected) is caught at manifest time;
    # both still pass through untouched to the REST engine. `params` values may be
    # plain scalars or the engine's incremental/resolver specs, so the type stays
    # permissive. `json` is aliased because `json` shadows a `BaseModel` attribute.
    params: dict[str, Any] | None = None
    json_body: dict[str, Any] | None = Field(default=None, alias="json")


class _ManifestResource(BaseModel):
    name: str = Field(min_length=1)
    endpoint: _ManifestEndpoint
    # How the upstream API orders this resource's rows. Incremental syncs commit
    # the high-watermark per batch for "asc"; for a source whose order is
    # unknown or descending, declaring "desc" here avoids skipping rows on a
    # resumed sync. Defaults to "asc" when omitted.
    sort_mode: Literal["asc", "desc"] | None = None


class _Manifest(BaseModel):
    """Structural schema for a user-provided REST API manifest. Only the fields
    this source reads are modelled; every other RESTAPIConfig field (paginator,
    data_selector, incremental, …) passes through untouched to the REST engine."""

    client: _ManifestClient
    resources: list[_ManifestResource] = Field(min_length=1)

    @model_validator(mode="after")
    def _resource_names_unique(self) -> "_Manifest":
        seen: set[str] = set()
        for resource in self.resources:
            if resource.name in seen:
                raise ValueError(f"Duplicate resource name: {resource.name!r}")
            seen.add(resource.name)
        return self


def validate_manifest(manifest: Any) -> None:
    """Validate the structural shape of a user-provided REST API manifest.

    Delegates to the :class:`_Manifest` schema. The safety of any URLs in
    the manifest is checked separately by :func:`validate_manifest_urls`,
    which needs the team_id for cloud-vs-self-hosted handling.
    """
    if not isinstance(manifest, dict):
        raise ManifestValidationError("Manifest must be a JSON object")
    try:
        _Manifest.model_validate(manifest)
    except ValidationError as exc:
        raise ManifestValidationError(_format_validation_errors(exc)) from exc


def _format_validation_errors(exc: ValidationError) -> str:
    """Render Pydantic's validation errors as a single user-facing string."""
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        messages.append(f"{location}: {message}" if location else message)
    return "; ".join(messages)


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
                "Set up a source using custom configured mappings. "
                "Define a REST API source by providing a manifest that follows the same shape "
                "as PostHog's built-in REST sources — see the docs for the field reference."
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
            # The SSRF guard raises BlockedHostError when a request — or a
            # pagination/redirect target that only appears at runtime — resolves
            # to an internal/private host. That is a deterministic policy
            # denial, never a transient error, so retrying it can never succeed.
            "Blocked request to host": "A request targeted an internal/private host, which is not allowed.",
            "Blocked connection to": "A request connected to an internal/private host, which is not allowed.",
        }

    def _assemble_manifest(self, config: CustomSourceConfig) -> dict[str, Any]:
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
        return manifest

    def validate_credentials(
        self, config: CustomSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            manifest = self._assemble_manifest(config)
        except ManifestValidationError as exc:
            return False, str(exc)

        ok, err = validate_manifest_urls(manifest, team_id)
        if not ok:
            return False, err

        # Probe every resource so we surface auth/connection errors at create-time
        # rather than waiting for the first sync. The auth/header setup comes from
        # the shared client config, so it is built once and reused across the
        # per-resource requests.
        client = manifest["client"]
        base_url = client["base_url"]

        headers: dict[str, str] = dict(client.get("headers") or {})
        # Build the probe's auth exactly the way the REST engine will at sync
        # time (`create_auth`) instead of reconstructing it by hand — so the
        # probe and the sync agree on which credential is sent and where
        # (header / query / cookie), and a malformed auth config surfaces here
        # as a clear error rather than crashing the first sync.
        try:
            probe_auth = create_auth(client.get("auth"))
        except (ValueError, TypeError) as exc:
            return False, f"Invalid auth configuration: {exc}"

        # The tracked session is always SSRF-guarded, so the probe itself
        # can't be steered at an internal host — defence in depth alongside
        # validate_manifest_urls. team_id carries the team's allowlist.
        session = make_tracked_session(headers=headers, team_id=team_id)

        for resource in manifest["resources"]:
            endpoint = resource.get("endpoint", {})
            method = (endpoint.get("method") or "GET").upper()
            path = endpoint.get("path", "")
            url = path if path.startswith(("http://", "https://")) else f"{base_url.rstrip('/')}/{path.lstrip('/')}"
            # Replay the configured query params and request body so the probe
            # matches what the sync sends — an endpoint that needs them shouldn't
            # answer differently at probe vs sync time.
            probe_params = _static_probe_params(endpoint.get("params"))
            probe_json = endpoint.get("json")
            try:
                response = session.request(
                    method, url, params=probe_params or None, json=probe_json, auth=probe_auth, timeout=15
                )
            except Exception as exc:
                return False, f"Resource {resource['name']!r}: could not reach {url}: {exc}"

            # Only an auth rejection (401/403) is a credential problem. Other
            # statuses — 404 (resource not yet provisioned), 405, 429 (rate
            # limited during the probe burst), 5xx — are not credential errors
            # and must not block source creation; a real, persistent failure
            # surfaces on the first sync instead.
            if response.status_code in (401, 403):
                return False, (
                    f"Resource {resource['name']!r}: the upstream API rejected the request with "
                    f"HTTP {response.status_code} from {url} — check the configured auth credentials: "
                    f"{response.text[:200]}"
                )

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

        ok, err = validate_manifest_urls(manifest, team_id)
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
        try:
            manifest = self._assemble_manifest(config)
            ok, err = validate_manifest_urls(manifest, inputs.team_id)
            if not ok:
                raise ManifestValidationError(err or "Manifest URL validation failed")

            chosen = next(
                (r for r in manifest["resources"] if isinstance(r, dict) and r.get("name") == inputs.schema_name),
                None,
            )
            if chosen is None:
                raise ValueError(f"Resource {inputs.schema_name!r} not found in config")
        except ValueError as exc:
            # A malformed manifest or a missing resource is a permanent,
            # deterministic failure — retrying the sync cannot fix it. Raise
            # NonRetryableException (the only type Temporal treats as
            # non-retryable for this activity) so the job fails fast instead of
            # burning the whole retry budget on an error that will always recur.
            raise NonRetryableException(str(exc)) from exc

        single_resource_manifest = cast(
            RESTAPIConfig,
            {**manifest, "resources": [_strip_engine_unsupported_incremental_keys(chosen)]},
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

        # The manifest declares the upstream's row ordering; default "asc" to
        # match PostHog's other REST sources. An incorrect "asc" assumption on a
        # non-ascending API can skip rows on a resumed incremental sync.
        #
        # "desc" only defers committing the high-watermark until the run finishes
        # (so a partial run can't advance the cursor past rows it never reached on
        # the next scheduled sync). It does NOT make a single run resumable: the
        # generic REST engine has no earliest-value sweep, so an interrupted "desc"
        # run restarts from the newest page rather than continuing older rows. This
        # is deliberately non-resumable — duplicate work is collapsed by
        # primary_keys, and the only failure mode is an endpoint too large to
        # finish within one worker window. A proper fix would slice the cursor into
        # windows with per-window state (cf. Airbyte's DatetimeBasedCursor), which
        # the generic engine doesn't support today.
        sort_mode: SortMode = "desc" if chosen.get("sort_mode") == "desc" else "asc"

        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: resource,
            primary_keys=primary_keys,
            partition_count=1,
            partition_size=1,
            partition_mode="md5",
            sort_mode=sort_mode,
        )


def _static_probe_params(params: Any) -> dict[str, Any]:
    """The literal query params safe to replay in the create-time probe.

    A RESTAPIConfig ``params`` map can hold the engine's incremental / parent-
    resolver specs (dict values) that are only resolved against cursor or parent
    state at sync time — the probe has neither, so it forwards just the plain
    (non-dict) values and lets the engine handle the rest on the first sync.
    """
    if not isinstance(params, dict):
        return {}
    return {key: value for key, value in params.items() if not isinstance(value, dict)}


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


def _incremental_field_type(raw: Any) -> IncrementalFieldType:
    """Map a manifest-declared cursor type to an :class:`IncrementalFieldType`.

    Defaults to ``DateTime`` — the common case for REST cursors — but a manifest
    can declare ``cursor_type`` (``integer``, ``date``, ``timestamp``, …) so an
    integer or string cursor is stored and compared with the right type rather
    than being misinterpreted as a timestamp.
    """
    if isinstance(raw, str):
        try:
            return IncrementalFieldType(raw.strip().lower())
        except ValueError:
            pass
    return IncrementalFieldType.DateTime


# Keys the Custom source understands on ``endpoint.incremental`` that the generic
# REST engine's ``Incremental(**config)`` constructor does NOT accept. They inform
# how the cursor is typed (see ``_incremental_field_type``) but must be removed
# before the engine builds its incremental tracker, or it raises an unexpected
# keyword-argument error at sync setup.
_ENGINE_UNSUPPORTED_INCREMENTAL_KEYS = frozenset({"cursor_type"})


def _strip_engine_unsupported_incremental_keys(resource: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``resource`` with REST-engine-incompatible keys removed
    from ``endpoint.incremental``. The input is left untouched so schema typing
    can still read the full incremental config."""
    endpoint = resource.get("endpoint")
    if not isinstance(endpoint, dict):
        return resource
    incremental = endpoint.get("incremental")
    if not isinstance(incremental, dict) or not _ENGINE_UNSUPPORTED_INCREMENTAL_KEYS.intersection(incremental):
        return resource
    cleaned = {k: v for k, v in incremental.items() if k not in _ENGINE_UNSUPPORTED_INCREMENTAL_KEYS}
    return {**resource, "endpoint": {**endpoint, "incremental": cleaned}}


def _schema_from_resource(resource: dict[str, Any]) -> SourceSchema:
    name = resource["name"]
    endpoint = resource.get("endpoint", {})
    incremental_cfg = endpoint.get("incremental") if isinstance(endpoint, dict) else None

    incremental_fields: list[IncrementalField] = []
    if isinstance(incremental_cfg, dict):
        cursor_path = incremental_cfg.get("cursor_path")
        if isinstance(cursor_path, str) and cursor_path:
            cursor_type = _incremental_field_type(incremental_cfg.get("cursor_type"))
            incremental_fields = [
                IncrementalField(
                    label=cursor_path,
                    field=cursor_path,
                    type=cursor_type,
                    field_type=cursor_type,
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
