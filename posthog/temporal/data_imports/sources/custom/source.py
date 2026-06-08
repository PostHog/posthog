import copy
import json
import graphlib
from typing import Any, Literal, Optional, cast
from urllib.parse import urlparse

from django.conf import settings

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from requests import Response
from urllib3.util.retry import Retry

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.cloud_utils import is_cloud
from posthog.temporal.data_imports.pipelines.pipeline.typings import SortMode, SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.mixins import _is_host_safe
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.auth import auth_secret_values
from posthog.temporal.data_imports.sources.common.rest_source.config_setup import (
    build_resource_dependency_graph,
    create_auth,
)
from posthog.temporal.data_imports.sources.common.rest_source.utils import resolve_request_url
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import CustomSourceConfig
from posthog.temporal.data_imports.util import NonRetryableException

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField, IncrementalFieldType

# Credential keys that must NOT appear inline in the manifest — they belong in
# the dedicated secret `auth_*` config fields so the API layer can redact them.
INLINE_SECRET_KEYS = ("token", "api_key", "password")

# Outbound create-time probe tunables. The probe runs inline on the API request
# thread, the same as business_knowledge's URL fetch, so it borrows that feature's
# limits (products/business_knowledge/backend/constants.py): short connect/read
# timeouts and a hard upper bound on declared resources. Defined locally rather
# than imported so data_imports doesn't couple to an unrelated product.
PROBE_CONNECT_TIMEOUT = 5
PROBE_READ_TIMEOUT = 10
# Auth/header config is shared across resources and the probe only acts on 401/403,
# so one reachable resource validates the credential. Probe a small prefix instead
# of one request per declared resource — otherwise the endpoint is an on-demand
# outbound-request amplifier (one API call -> N outbound requests).
PROBE_MAX_RESOURCES = 5
# Bytes read from a 401/403 body for the error snippet. The probe opens responses
# with stream=True and never ingests the body, so a bounded slice keeps a large or
# hostile response from being buffered into worker memory (cf. URL_MAX_BYTES, sized
# down here because the probe only needs a short diagnostic snippet).
PROBE_ERROR_SNIPPET_BYTES = 2048
# Upper bound on declared resources, matching business_knowledge MAX_URLS_PER_SOURCE.
MAX_MANIFEST_RESOURCES = 500


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
    resources: list[_ManifestResource] = Field(min_length=1, max_length=MAX_MANIFEST_RESOURCES)

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

    _validate_resource_graph(manifest)


def _validate_resource_graph(manifest: dict[str, Any]) -> None:
    """Surface parent/child fan-out errors at create-time instead of first sync.

    Reuses the REST engine's own :func:`build_resource_dependency_graph` so the
    rules can't drift from what the engine enforces at runtime: a child's
    ``type: "resolve"`` param must reference a resource that exists, must be
    bound in the path (``/forms/{form_id}/responses`` — query-param resolve is
    not supported by the engine), at most one resolve param per resource, and no
    dependency cycles (forced by ``static_order``). The graph builder mutates the
    resources it inspects (binds path params), so it runs on a deep copy and
    never touches the stored manifest.
    """
    try:
        graph, _, _ = build_resource_dependency_graph(
            copy.deepcopy(manifest.get("resource_defaults") or {}),
            copy.deepcopy(manifest["resources"]),
        )
        list(graph.static_order())
    except (ValueError, NotImplementedError, graphlib.CycleError) as exc:
        raise ManifestValidationError(str(exc)) from exc


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

    base_host = _url_hostname(base_url)
    for resource in manifest["resources"]:
        # Resolve exactly as the engine will (so a whitespace/case-disguised absolute path
        # is caught), then only re-vet resources that resolve to a *different* host than
        # base_url — `_is_host_safe` does a DNS lookup, so don't re-resolve base per resource.
        resolved = _endpoint_request_url(base_url, resource.get("endpoint"))
        if resolved is None or _url_hostname(resolved) == base_host:
            continue
        ok, err = _check_url(resolved, team_id)
        if not ok:
            return False, f"Resource {resource['name']!r}: {err}"

    return True, None


def _check_url(url: str, team_id: int) -> tuple[bool, str | None]:
    # `_url_hostname` mirrors the real connect host (backslash/whitespace-normalized) so the
    # validator can't be fooled into vetting a different host than the request reaches.
    hostname = _url_hostname(url)
    if not hostname:
        return False, f"URL {url!r} is missing a hostname"
    if is_cloud() and urlparse(url).scheme != "https":
        return False, f"URL {url!r} must use https:// on PostHog Cloud"
    return _is_host_safe(hostname, team_id)


class _LeaveMissing(dict):
    """Format mapping that leaves unknown ``{name}`` placeholders untouched."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _endpoint_request_url(base_url: str, endpoint: Any) -> str | None:
    """The URL an endpoint will send a request — and the credential — to.

    The REST engine binds scalar ``params`` into the path (``_bind_path_params`` runs
    ``path.format(**params)``) and then resolves it against ``base_url`` via
    ``resolve_request_url``. We do exactly the same here, so a template like ``"{target}"``
    (``params={"target": "https://attacker/"}``) or ``"{scheme}://attacker/"``
    (``params={"scheme": "https"}``) — and any whitespace/case/encoding-disguised absolute
    URL — resolves to the same destination the runtime would request. Returns ``None`` for a
    non-dict endpoint or a missing/non-string path. (SSRF to internal hosts is separately
    caught at request time by the transport-layer guard; this is about detecting a *new
    destination* for the credential re-entry check.)
    """
    if not isinstance(endpoint, dict):
        return None
    path = endpoint.get("path")
    if not isinstance(path, str):
        return None

    params = endpoint.get("params")
    bindable = (
        _LeaveMissing({name: value for name, value in params.items() if isinstance(value, str)})
        if isinstance(params, dict)
        else _LeaveMissing()
    )
    try:
        resolved = path.format_map(bindable)
    except (ValueError, IndexError, KeyError):
        # Malformed / positional format string — it's re-vetted at request time anyway.
        resolved = path

    return resolve_request_url(base_url, resolved)


def manifest_request_hosts(manifest_json: Any) -> frozenset[str]:
    """Hostnames a stored manifest will send requests — and the credential — to.

    Lets the API layer detect when an update retargets the source at a new host
    so it can require the credential to be re-entered: an editor who can't read
    the stored secret must not be able to redirect it to a server they control.
    Returns an empty set for anything unparseable — the caller treats "no hosts"
    as "nothing new", and a malformed manifest is rejected elsewhere.
    """
    if not isinstance(manifest_json, str):
        return frozenset()
    try:
        manifest = json.loads(manifest_json)
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(manifest, dict):
        return frozenset()

    client = manifest.get("client")
    base_url = client.get("base_url") if isinstance(client, dict) else None
    # Resolve resource paths against base_url the same way the engine does. With no usable
    # base_url an absolute resource path still has a host; a relative one is left hostless
    # (its destination is unknown) — the manifest is rejected elsewhere for the missing base.
    base_for_resolve = base_url if isinstance(base_url, str) else ""

    urls: list[str] = [base_url] if isinstance(base_url, str) else []
    resources = manifest.get("resources")
    if isinstance(resources, list):
        for resource in resources:
            endpoint = resource.get("endpoint") if isinstance(resource, dict) else None
            resolved = _endpoint_request_url(base_for_resolve, endpoint)
            if resolved is not None:
                urls.append(resolved)

    # `_url_hostname` returns an already-lowercased host.
    hosts = {host for url in urls if (host := _url_hostname(url))}
    return frozenset(hosts)


def _url_hostname(url: str) -> str | None:
    """The host the HTTP client will actually connect to.

    `urlparse` treats a backslash — and its ``%5c`` encoding — as ordinary
    userinfo, so ``https://evil.example\\@trusted.example/`` parses as host
    ``trusted.example`` here, while requests/urllib3 (per the WHATWG URL rules)
    treat ``\\`` as a path separator and connect to ``evil.example``. Normalizing
    those to ``/`` before parsing keeps the retarget guard aligned with the real
    destination, so an ambiguous-authority URL can't smuggle the credential to a
    new host while appearing unchanged.
    """
    normalized = url.replace("\\", "/").replace("%5c", "/").replace("%5C", "/")
    return urlparse(normalized).hostname


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
            releaseStatus=ReleaseStatus.ALPHA,
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

        # Probe a small prefix of resources so we surface auth/connection errors
        # at create-time rather than waiting for the first sync. The auth/header
        # setup comes from the shared client config, so it is built once and
        # reused across the per-resource requests.
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

        # The probe runs inline on the request thread, so keep it cheap and
        # bounded: no retries (don't multiply outbound volume at create time),
        # no redirects (Smokescreen re-resolves each hop; keep the credential
        # pinned to the validated host), and credential values registered for
        # redaction even when injected under a manifest-chosen param/header name
        # the denylist scrubber can't anticipate.
        session = make_tracked_session(
            headers=headers,
            redact_values=auth_secret_values(probe_auth),
            retry=Retry(total=0),
            allow_redirects=False,
        )

        # Fan-out child resources bind a parent row's field into their path
        # (`/forms/{form_id}/responses`), so they can't be reached without first
        # fetching a parent — skip them. Auth is shared across resources, so the
        # top-level resources still validate the credential. The engine's own
        # dependency map (not a local copy of its resolve-param detection) tells
        # us which resources are children.
        resolved = _resolved_param_map(manifest)
        probeable = [resource for resource in manifest["resources"] if resolved.get(resource.get("name")) is None]
        for resource in probeable[:PROBE_MAX_RESOURCES]:
            endpoint = resource.get("endpoint", {})
            method = (endpoint.get("method") or "GET").upper()
            path = endpoint.get("path", "")
            # Resolve via the shared helper so the probe hits the same host the sync will.
            url = resolve_request_url(base_url, path)
            # Replay the configured query params and request body so the probe
            # matches what the sync sends — an endpoint that needs them shouldn't
            # answer differently at probe vs sync time.
            probe_params = _static_probe_params(endpoint.get("params"))
            probe_json = endpoint.get("json")
            try:
                # stream=True so the body isn't buffered into memory; only a 401/403
                # snippet is read below, and the response is always closed.
                response = session.request(
                    method,
                    url,
                    params=probe_params or None,
                    json=probe_json,
                    auth=probe_auth,
                    timeout=(PROBE_CONNECT_TIMEOUT, PROBE_READ_TIMEOUT),
                    stream=True,
                )
            except Exception as exc:
                return False, f"Resource {resource['name']!r}: could not reach {url}: {exc}"

            # Only an auth rejection (401/403) is a credential problem. Other
            # statuses — 404 (resource not yet provisioned), 405, 429 (rate
            # limited during the probe burst), 5xx — are not credential errors
            # and must not block source creation; a real, persistent failure
            # surfaces on the first sync instead.
            try:
                if response.status_code in (401, 403):
                    return False, (
                        f"Resource {resource['name']!r}: the upstream API rejected the request with "
                        f"HTTP {response.status_code} from {url} — check the configured auth credentials: "
                        f"{_read_capped_text(response)}"
                    )
            finally:
                response.close()

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

            # The resources to run for this schema: `chosen` plus, when it's a
            # fan-out child, its ancestor chain (root first). The engine then
            # fetches each parent and issues one child request per parent row; the
            # ancestors drive the child transiently and aren't persisted — only
            # `chosen` is returned as its own table. A top-level resource is just
            # `[chosen]`, so a single code path handles both. See `_fanout_chain`
            # for why we pass this subset rather than the whole manifest.
            chain = _fanout_chain(manifest, inputs.schema_name)
        except ValueError as exc:
            # A malformed manifest, a missing resource, or a broken parent
            # reference is a permanent, deterministic failure — retrying the sync
            # cannot fix it. Raise NonRetryableException (the only type Temporal
            # treats as non-retryable for this activity) so the job fails fast
            # instead of burning the whole retry budget on an error that will
            # always recur.
            raise NonRetryableException(str(exc)) from exc

        chosen_name = chosen["name"]

        # Incremental is stripped from the ancestors (not `chosen`) so the run's
        # high-watermark — which belongs to `chosen` — isn't applied to a parent,
        # which would silently drop parent rows and, with them, their children.
        # Ancestors therefore full-scan every run, matching the built-in fan-out
        # sources (Typeform/Sentry).
        engine_resources = [_prepare_fanout_resource(r, is_child=r["name"] == chosen_name) for r in chain]
        engine_manifest = cast(RESTAPIConfig, {**manifest, "resources": engine_resources})

        resources = rest_api_resources(
            engine_manifest,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            db_incremental_field_last_value=(
                inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None
            ),
        )
        resource = next((r for r in resources if getattr(r, "name", None) == chosen_name), None)
        if resource is None:
            raise NonRetryableException(f"Resource {chosen_name!r} was not produced by the REST engine")

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


def _read_capped_text(response: Response) -> str:
    """Read at most ``PROBE_ERROR_SNIPPET_BYTES`` of a streamed body for an error snippet.

    The probe opens responses with ``stream=True`` and never ingests the body, so a
    bounded slice keeps a large or hostile upstream response from being materialized
    into worker memory. Reads the raw stream directly (rather than ``response.text``,
    which buffers and decompresses the whole body).

    ``decode_content=False`` is deliberate: it reads exactly ``PROBE_ERROR_SNIPPET_BYTES``
    raw bytes and never inflates a ``Content-Encoding: gzip`` body, so a decompression
    bomb can't expand a tiny read into megabytes. The snippet is only a human-readable
    diagnostic — a (rare) compressed error body just shows as bytes.
    """
    try:
        raw = response.raw.read(PROBE_ERROR_SNIPPET_BYTES, decode_content=False)
    except Exception:
        return ""
    return raw.decode("utf-8", errors="replace")


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


def _resolved_param_map(manifest: dict[str, Any]) -> dict[str, Any]:
    """The REST engine's parent-resolution map for the manifest, keyed by
    resource name. ``None`` marks a top-level resource; otherwise the value's
    ``resolve_config["resource"]`` names the parent it fans out from.

    Sourcing this from the engine's own ``build_resource_dependency_graph`` keeps
    the resolve-param shape (``{"type": "resolve", ...}``) defined in exactly one
    place — the engine — so the Custom source can't silently diverge from it if
    that shape ever changes. The graph builder mutates the resources it inspects,
    so it runs on a deep copy. Callers reach this only after ``validate_manifest``
    has already built the graph once, so it won't raise here.
    """
    _, _, resolved = build_resource_dependency_graph(
        copy.deepcopy(manifest.get("resource_defaults") or {}),
        copy.deepcopy(manifest["resources"]),
    )
    return resolved


def _fanout_chain(manifest: dict[str, Any], chosen_name: str) -> list[dict[str, Any]]:
    """Resources to hand the engine for ``chosen_name``: its fan-out ancestors
    (root first) then ``chosen`` itself, or just ``[chosen]`` for a top-level
    resource.

    We pass this subset, not the whole manifest, on purpose. The engine is lazy —
    resources it builds but we never iterate issue no requests — but it still
    runs ``setup_incremental_object`` for every resource it's given at build time,
    so an unrelated resource's config error would otherwise sink this schema's
    sync. Subsetting also lets ``_prepare_fanout_resource`` full-scan the
    ancestors (incremental stripped) so the child's high-watermark isn't
    misapplied to a parent. The parent graph comes from the engine via
    :func:`_resolved_param_map`, so resolve-param detection isn't re-implemented
    here; missing-parent and cycle errors are already rejected at manifest time.
    """
    resolved = _resolved_param_map(manifest)
    by_name: dict[str, dict[str, Any]] = {
        r["name"]: r for r in manifest["resources"] if isinstance(r, dict) and isinstance(r.get("name"), str)
    }
    names: list[str] = [chosen_name]
    seen: set[str] = {chosen_name}
    current = chosen_name
    while resolved.get(current) is not None:
        parent_name = resolved[current].resolve_config["resource"]
        if parent_name in seen:  # cycles are rejected at manifest time; guard against a logic error
            break
        names.append(parent_name)
        seen.add(parent_name)
        current = parent_name
    return [by_name[name] for name in reversed(names)]


def _prepare_fanout_resource(resource: dict[str, Any], *, is_child: bool) -> dict[str, Any]:
    """Ready a resource in a fan-out chain for the REST engine.

    The chosen child keeps its incremental config (the run's high-watermark is
    its cursor). Ancestors are stripped of incremental config so the single
    ``db_incremental_field_last_value`` — which belongs to the child — can't be
    misapplied to a parent and silently drop parent rows (and with them their
    children). Both still have engine-incompatible keys (``cursor_type``)
    stripped.
    """
    prepared = _strip_engine_unsupported_incremental_keys(resource)
    if is_child:
        return prepared
    return _without_endpoint_incremental(prepared)


def _without_endpoint_incremental(resource: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``resource`` with ``endpoint.incremental`` removed."""
    endpoint = resource.get("endpoint")
    if not isinstance(endpoint, dict) or "incremental" not in endpoint:
        return resource
    return {**resource, "endpoint": {k: v for k, v in endpoint.items() if k != "incremental"}}


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
