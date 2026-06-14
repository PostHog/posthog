import copy
import json
import graphlib
from datetime import date
from typing import Any, Literal, NamedTuple, Optional, cast
from urllib.parse import urlparse

import structlog
from jsonpath_ng.exceptions import JSONPathError
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
from posthog.temporal.data_imports.sources.common.rest_source.typing import (
    EndpointResource,
    EndpointResourceBase,
    ResolvedParam,
)
from posthog.temporal.data_imports.sources.common.rest_source.utils import exclude_keys, resolve_request_url
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import CustomSourceConfig
from posthog.temporal.data_imports.util import NonRetryableException

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField, IncrementalFieldType

# Credential keys that must NOT appear inline in the manifest — they belong in
# the dedicated secret `auth_*` config fields so the API layer can redact them.
INLINE_SECRET_KEYS = ("token", "api_key", "password")

logger = structlog.get_logger(__name__)

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
# Upper bound on the number of resources (tables/endpoints) a single custom
# source may declare. Also bounds the create-time outbound-request amplifier.
MAX_MANIFEST_RESOURCES = 50

# Upper bound on the number of custom sources a single team/project may create.
# Enforced in the external_data_source create endpoint.
MAX_CUSTOM_SOURCES_PER_TEAM = 5


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


def validate_manifest_structure(manifest: Any) -> None:
    """Validate only the structural shape of a manifest, via the
    :class:`_Manifest` schema.

    This is the validation level used on sync and schema-listing reads of
    already-stored manifests: it must stay permissive enough that tightening
    the rules can never brick a deployed source's syncs. Graph-level fan-out
    errors are checked separately by :func:`_validate_resource_graph` on the
    API validation paths (`validate_credentials`), and per-schema at sync time
    by :func:`_fanout_chain`.
    """
    if not isinstance(manifest, dict):
        raise ManifestValidationError("Manifest must be a JSON object")
    try:
        _Manifest.model_validate(manifest)
    except ValidationError as exc:
        raise ManifestValidationError(_format_validation_errors(exc)) from exc


def _validate_resource_graph(manifest: dict[str, Any]) -> dict[str, Optional[ResolvedParam]]:
    """Surface parent/child fan-out errors at create-time instead of first sync.

    Reuses the REST engine's own :func:`build_resource_dependency_graph` so the
    rules can't drift from what the engine enforces at runtime: a child's
    ``type: "resolve"`` param must reference a resource that exists, must be
    bound in the path (``/forms/{form_id}/responses`` — query-param resolve is
    not supported by the engine), at most one resolve param per resource, and no
    dependency cycles (forced by ``static_order``). The graph builder mutates the
    resources it inspects (binds path params), so it runs on a deep copy and
    never touches the stored manifest.

    On top of the engine's rules, nesting is capped at one level: a parent must
    itself be top-level. The engine supports deeper chains, but each extra level
    multiplies the per-sync request volume by the parent's row count and every
    ancestor full-scans on every run — and no shipped fan-out source (PostHog
    built-ins, or any of Airbyte's declarative connectors) uses more than one
    level. Starting strict is deliberately cheap to relax later; loosening the
    cap is backwards-compatible, tightening it would break stored manifests.

    Returns the engine's parent-resolution map (resource name -> resolve param,
    ``None`` for top-level resources) so callers that need it — the probe's
    child filter — don't rebuild the graph.
    """
    try:
        graph, resource_map, resolved = _build_resource_graph(manifest)
        list(graph.static_order())
    except KeyError as exc:
        # A resolve param missing "resource"/"field" raises KeyError from deep
        # inside the engine — surface it as a validation error, not a 500.
        raise ManifestValidationError(f"A resolve param is missing the required key {exc}") from exc
    except JSONPathError as exc:
        # The resolve param's "field" is a JSONPath, compiled inside the engine;
        # a malformed expression raises a bare-Exception subclass.
        raise ManifestValidationError(f"A resolve param's field is not a valid JSONPath: {exc}") from exc
    except graphlib.CycleError as exc:
        # str(CycleError) is the raw args tuple — render the cycle readably.
        cycle = exc.args[1] if len(exc.args) > 1 else []
        rendered = " -> ".join(str(name) for name in cycle)
        raise ManifestValidationError(f"Resources form a dependency cycle: {rendered}") from exc
    except (ValueError, NotImplementedError) as exc:
        raise ManifestValidationError(str(exc)) from exc

    client = manifest.get("client")
    base_url = client.get("base_url") if isinstance(client, dict) else None
    for name, resolved_param in resolved.items():
        if resolved_param is None:
            continue
        parent = resolved_param.resolve_config["resource"]
        if resolved.get(parent) is not None:
            raise ManifestValidationError(
                f"Resource {name!r} depends on {parent!r}, which itself depends on another resource — "
                "a resource can only depend on a top-level resource (one level of nesting)"
            )
        # The parent placeholder is filled with uncontrolled upstream data at
        # sync time, then the engine resolves the path against base_url. A
        # placeholder positioned where it can supply the URL's authority lets that
        # parent value redirect the authenticated request — and its credential —
        # off base_url: a leading placeholder (`{form_id}/...`) can be a full
        # `https://attacker/...`, and a literal scheme prefix (`https:{form_id}`)
        # lets `//attacker/...` take over the authority. Neither the create-time
        # host validator nor the update retarget guard can see this — they only
        # ever inspect the literal placeholder. The path comes from `resource_map`
        # (defaults merged, scalar params already bound), so only the resolve
        # placeholder survives in the same string the request is built from.
        endpoint = resource_map[name].get("endpoint")
        path = endpoint.get("path", "") if isinstance(endpoint, dict) else ""
        if (
            isinstance(path, str)
            and isinstance(base_url, str)
            and _placeholder_escapes_base(path, resolved_param.param_name, base_url)
        ):
            raise ManifestValidationError(
                f"Resource {name!r}: the parent placeholder {{{resolved_param.param_name}}} must sit within the path "
                "of the base URL (e.g. /forms/{form_id}/responses) — it must not start the path or follow a scheme "
                "like 'https:', so the bound parent value can't redirect the request off the manifest's base URL"
            )
    return resolved


def _validate_incremental_configs(manifest: dict[str, Any]) -> None:
    """Reject incremental config values that would deterministically crash at sync time.

    The structural schema doesn't model ``endpoint.incremental``, so a hand-authored
    non-string ``datetime_format`` would otherwise only surface mid-sync, and only
    from the second sync onward (formatting needs a stored watermark).
    """
    for resource in manifest.get("resources") or []:
        if not isinstance(resource, dict):
            continue
        endpoint = resource.get("endpoint")
        incremental = endpoint.get("incremental") if isinstance(endpoint, dict) else None
        if not isinstance(incremental, dict):
            continue
        datetime_format = incremental.get("datetime_format")
        if datetime_format is not None and not isinstance(datetime_format, str):
            raise ManifestValidationError(
                f"Resource {resource.get('name')!r}: endpoint.incremental.datetime_format must be a string "
                'strftime pattern (e.g. "%Y-%m-%dT%H:%M:%SZ")'
            )


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


# Probe values substituted for a fan-out child's resolve placeholder to test
# whether uncontrolled parent data bound there could move the request — and the
# credential — off base_url's host. Each models a different escape technique: a
# full absolute URL (placeholder is the first/only path segment), an
# authority-only value (a literal ``scheme:`` prefix lets ``//host`` take over),
# and a bare host (placeholder sits in the authority of a ``scheme://`` prefix).
# The ``.invalid`` TLD never resolves and this is a pure string check — no I/O.
_PLACEHOLDER_ESCAPE_SENTINELS = ("https://sentinel.invalid/x", "//sentinel.invalid/x", "sentinel.invalid")


def _placeholder_escapes_base(path: str, param_name: str, base_url: str) -> bool:
    """True if binding the resolve placeholder ``{param_name}`` in ``path`` could
    move the request to a host other than ``base_url``'s.

    The placeholder is filled with uncontrolled upstream data at sync time, then
    the engine resolves the path against ``base_url`` exactly as
    :func:`resolve_request_url` does. We substitute attacker-shaped sentinels for
    the placeholder and check whether any resolves to a different host — catching
    not just a leading placeholder (``{form_id}/responses``) but a literal
    ``scheme:`` prefix that lets the bound value supply the authority
    (``https:{form_id}/responses`` with ``form_id="//attacker/x"`` resolves to the
    attacker host). A position that keeps the placeholder strictly inside the path
    (``/forms/{form_id}/responses``) leaves the host unchanged and passes.
    """
    base_host = _url_hostname(base_url)
    if not base_host:
        # A base_url with no host is rejected separately by validate_manifest_urls;
        # don't raise a confusing placeholder error for it here.
        return False
    placeholder = "{" + param_name + "}"
    for sentinel in _PLACEHOLDER_ESCAPE_SENTINELS:
        probed = path.replace(placeholder, sentinel)
        if _url_hostname(resolve_request_url(base_url, probed)) != base_host:
            return True
    return False


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
        # Structural validation only — no resource-graph checks. This runs on
        # every sync and schema listing of already-stored manifests, so a
        # graph problem on one resource must not take down the source's other
        # schemas (graph rules are enforced on the API validation paths in
        # `validate_credentials`, and per-schema at sync time in `_fanout_chain`).
        validate_manifest_structure(manifest)
        _inject_auth_secrets(manifest, config)
        return manifest

    def validate_credentials(
        self, config: CustomSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            manifest = self._assemble_manifest(config)
            # Graph-level fan-out rules apply on every validation path —
            # including updates that don't touch the manifest and schema-scoped
            # read checks. Builder-authored manifests are always graph-valid,
            # so a stored manifest tripping this means hand-authored JSON that
            # never synced; failing the API call with a pointed message is
            # preferable to carrying a permanent leniency mode. The returned
            # map feeds the probe's child filter below.
            resolved = _validate_resource_graph(manifest)
            _validate_incremental_configs(manifest)
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

            # The resources to run for this schema: the chosen resource plus,
            # when it's a fan-out child, its ancestor chain (root first) — see
            # `_fanout_chain` for the full rationale. Ancestors are stripped of
            # incremental config so the run's high-watermark — which belongs to
            # the chosen resource — can't be misapplied to a parent and silently
            # drop parent rows (and with them their children); they full-scan
            # every run, matching the built-in fan-out sources (Typeform/Sentry).
            chain = _fanout_chain(manifest, inputs.schema_name)
            chosen = chain.child
            engine_resources = [
                *(_without_incremental_config(r) for r in chain.ancestors),
                _strip_engine_unsupported_incremental_keys(chain.child),
            ]
            engine_manifest = cast(RESTAPIConfig, {**manifest, "resources": engine_resources})

            # The engine serializes a datetime watermark via str() (space-separated),
            # which strict APIs reject — format it to the declared wire format first.
            last_value = inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None
            last_value = _format_incremental_cursor(last_value, chosen)

            # Inside the try block: the engine raises deterministic ValueErrors at
            # build time for config problems the create-time checks can't see
            # (e.g. `include_from_parent` on a resource with no resolve param).
            resources = rest_api_resources(
                engine_manifest,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                db_incremental_field_last_value=last_value,
            )
        except ValueError as exc:
            # A malformed manifest, a missing resource, or a broken parent
            # reference is a permanent, deterministic failure — retrying the sync
            # cannot fix it. Raise NonRetryableException (the only type Temporal
            # treats as non-retryable for this activity) so the job fails fast
            # instead of burning the whole retry budget on an error that will
            # always recur.
            raise NonRetryableException(str(exc)) from exc

        resource = next((r for r in resources if getattr(r, "name", None) == inputs.schema_name), None)
        if resource is None:
            raise NonRetryableException(f"Resource {inputs.schema_name!r} was not produced by the REST engine")

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
        #
        # Fan-out children always get the deferred-commit ("desc") behavior: their
        # rows arrive grouped per parent, never globally cursor-ascending, so an
        # "asc" per-batch commit after an interruption would set the watermark past
        # later parents' older rows and permanently skip them.
        sort_mode: SortMode = "desc" if (chain.is_fanout_child or chosen.get("sort_mode") == "desc") else "asc"

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
# REST engine's ``Incremental(**config)`` constructor does NOT accept. They must be
# removed before the engine builds its incremental tracker, or it raises an
# unexpected keyword-argument error at sync setup.
_ENGINE_UNSUPPORTED_INCREMENTAL_KEYS = frozenset({"cursor_type", "datetime_format"})


def _format_incremental_cursor(value: Any, chosen: dict[str, Any]) -> Any:
    """Render a datetime/date high-watermark as a string for the REST engine.

    The engine binds the watermark via ``str()``, whose space-separated datetime
    rendering strict APIs (e.g. Typeform) reject. The resource's
    ``endpoint.incremental.datetime_format`` strftime pattern controls the wire
    format, defaulting to ISO-8601; non-datetime cursors pass through untouched.

    A non-string ``datetime_format`` raises ``ManifestValidationError`` (non-retryable)
    instead of strftime's ``TypeError``, which Temporal would retry — a backstop for
    manifests stored before ``_validate_incremental_configs`` existed.
    """
    # `datetime` is a subclass of `date`, so this matches both.
    if not isinstance(value, date):
        return value
    endpoint = chosen.get("endpoint")
    incremental = endpoint.get("incremental") if isinstance(endpoint, dict) else None
    datetime_format = incremental.get("datetime_format") if isinstance(incremental, dict) else None
    if datetime_format is not None and not isinstance(datetime_format, str):
        raise ManifestValidationError(
            f"Resource {chosen.get('name')!r}: endpoint.incremental.datetime_format must be a string "
            'strftime pattern (e.g. "%Y-%m-%dT%H:%M:%SZ")'
        )
    return value.strftime(datetime_format) if datetime_format else value.isoformat()


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
    cleaned = exclude_keys(incremental, _ENGINE_UNSUPPORTED_INCREMENTAL_KEYS)
    return {**resource, "endpoint": {**endpoint, "incremental": cleaned}}


def _build_resource_graph(
    manifest: dict[str, Any],
) -> tuple[Any, dict[str, EndpointResource], dict[str, Optional[ResolvedParam]]]:
    """Run the REST engine's dependency-graph builder on a deep copy of the
    manifest. The builder binds path params in place, so it must never see the
    stored manifest's resources — hence the copy.
    """
    return build_resource_dependency_graph(
        cast(EndpointResourceBase, copy.deepcopy(manifest.get("resource_defaults") or {})),
        cast("list[str | EndpointResource]", copy.deepcopy(manifest["resources"])),
    )


class FanoutChain(NamedTuple):
    """The resources a schema's sync hands the engine: the chosen resource plus
    its fan-out ancestors (root first). The single source of truth for whether
    the chosen resource is a fan-out child — callers must not re-derive that
    from names or chain length."""

    ancestors: list[dict[str, Any]]
    child: dict[str, Any]

    @property
    def is_fanout_child(self) -> bool:
        return bool(self.ancestors)


def _fanout_chain(manifest: dict[str, Any], chosen_name: str) -> FanoutChain:
    """The :class:`FanoutChain` for ``chosen_name``: its fan-out ancestors
    (root first) plus ``chosen`` itself; a top-level resource has no ancestors.

    We pass this subset, not the whole manifest, on purpose. The engine is lazy —
    resources it builds but we never iterate issue no requests — but it still
    runs ``setup_incremental_object`` for every resource it's given at build time,
    so an unrelated resource's config error would otherwise sink this schema's
    sync. Subsetting also lets the caller full-scan the ancestors (via
    ``_without_incremental_config``) so the child's high-watermark isn't
    misapplied to a parent. The parent graph comes from the engine's own
    ``build_resource_dependency_graph``, so resolve-param detection isn't
    re-implemented here.

    Raises ``ValueError`` when ``chosen_name`` isn't in the manifest.
    """
    by_name: dict[str, dict[str, Any]] = {
        r["name"]: r for r in manifest["resources"] if isinstance(r, dict) and isinstance(r.get("name"), str)
    }
    chosen = by_name.get(chosen_name)
    if chosen is None:
        raise ValueError(f"Resource {chosen_name!r} not found in config")
    try:
        _, _, resolved = _build_resource_graph(manifest)
    except (ValueError, NotImplementedError, KeyError, JSONPathError) as exc:
        # Graph rules are enforced at create/update time, but a stored manifest
        # can predate them. A graph error on an UNRELATED resource must not sink
        # this schema's sync — fall back to handing the engine just the chosen
        # resource (the pre-fan-out behavior). If the chosen resource itself is
        # the broken one, the engine rejects it at build time with the
        # underlying error, which the caller converts to a non-retryable failure.
        # Logged so the size of the predates-the-rules population is measurable;
        # once this stops firing in production the fallback can be deleted.
        logger.warning(
            "custom_source_fanout_graph_fallback",
            schema_name=chosen_name,
            error=str(exc),
        )
        return FanoutChain(ancestors=[], child=chosen)
    ancestor_names: list[str] = []
    seen: set[str] = {chosen_name}
    current = chosen_name
    while (resolved_param := resolved.get(current)) is not None:
        parent_name = resolved_param.resolve_config["resource"]
        if parent_name in seen:
            # The graph builder itself doesn't reject cycles (only the
            # create-time `static_order` check does), so a stored manifest can
            # still carry one — fail loudly rather than loop or truncate.
            raise ValueError(f"Resource {chosen_name!r} is part of a dependency cycle")
        ancestor_names.append(parent_name)
        seen.add(parent_name)
        current = parent_name
    return FanoutChain(ancestors=[by_name[name] for name in reversed(ancestor_names)], child=chosen)


def _without_incremental_config(resource: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``resource`` with every incremental form removed.

    The engine builds an incremental tracker from EITHER ``endpoint.incremental``
    OR a params-style ``{"type": "incremental", ...}`` spec (see the engine's
    ``setup_incremental_object``) — both must go, or the run's high-watermark
    would still be injected into this resource's start param.
    """
    endpoint = resource.get("endpoint")
    if not isinstance(endpoint, dict):
        return resource
    cleaned = exclude_keys(endpoint, {"incremental"})
    params = cleaned.get("params")
    if isinstance(params, dict):
        cleaned["params"] = {
            key: value
            for key, value in params.items()
            if not (isinstance(value, dict) and value.get("type") == "incremental")
        }
    return {**resource, "endpoint": cleaned}


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
