"""The activity log record of a hog function test that delivers real requests.

A test with `mock_async_functions` off runs the submitted code with real `fetch` calls and the
credentials of the integrations its inputs name. The record keeps what an investigator needs to
answer who ran which code with which integrations, and never an input value: values can hold
secrets, and the test resolves secret inputs to plaintext before it runs.
"""

import re
import ipaddress
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import urlsplit

import idna
import requests
import structlog
import tldextract
from prometheus_client import Counter

from posthog.hogql.parser import parse_string_template

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    ActivityLog,
    Detail,
    update_activity_context,
)

from products.cdp.backend.validation import collect_inputs

if TYPE_CHECKING:
    from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)

TEST_RUN_REQUEST_ORIGINS_MISSING = Counter(
    "test_run_request_origins_missing",
    "Test runs with real requests whose audit row cannot say where the requests went",
    labelnames=["scope"],
)

_MAX_REQUEST_ORIGINS = 100
_DEFAULT_PORTS = {"http": 80, "https": 443}
_REDACTED = "***REDACTED***"
_ORIGIN_PARTS = re.compile(r"^([a-z][a-z0-9+.-]*://)([^/:\[\]]+)(:\d+)?$")
# The bundled suffix list, so a test run never fetches it over the network.
# Private suffixes stay out, so a stored secret used as the tenant on a shared host, such as
# <secret>.workers.dev, is redacted as a subdomain.
_DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=())
# A shorter value matches ordinary host fragments, so it is redacted only where it fills a whole label.
_MIN_SECRET_LENGTH = 8

_CONTEXT_FIELDS = ("hog", "inputs", "inputs_schema", "mappings")
# The worker runs these templates with their own executors, which send real requests even when the test mocks.
_UNMOCKED_TEMPLATE_PREFIXES = ("native-", "segment-")
# Hog templates are parsed, but the parser does not read Liquid, so a Liquid input is matched by pattern.
_LIQUID_INPUT_REFERENCE = re.compile(r"""inputs(?:\.([A-Za-z_]\w*)|\[\s*['"]([^'"]+)['"]\s*\])""")


# `ActivityDetailEncoder` serializes a context through `__dict__`, which a slotted class leaves empty.
@frozen(slots=False)
class HogFunctionTestRunContext(ActivityContextBase):
    mock_async_functions: bool
    integration_ids: list[int]
    input_keys: list[str]
    mapping_input_keys: list[str]
    # The other inputs that each input's template reads, by input key. An input can read an integration
    # input, so this shows where an integration value can flow.
    input_references: dict[str, list[str]]
    mapping_input_references: dict[str, list[str]]
    hog: Optional[str]
    request_origins: Optional[list[str]] = None


def integration_ids_in_value(value: Any) -> Iterable[int]:
    # An `integration_multi` input holds a list. The `{"integrationId": ...}` form matches
    # integration_usage.py, so the record can name an id the worker skips but never miss one.
    if isinstance(value, dict):
        value = value.get("integrationId")
    for candidate in value if isinstance(value, list) else [value]:
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            yield candidate


def _integration_ids(effective: dict[str, Any], mappings: list[dict[str, Any]]) -> set[int]:
    # Mirrors `loadIntegrationInputs` in nodejs/src/cdp/services/hog-inputs.service.ts. The worker merges
    # the inputs of each mapping, in order, over the top-level inputs, and reads every schema against that
    # merged set. A mapping input can therefore replace the integration that a top-level input names.
    schemas: list[Any] = []
    merged: dict[str, Any] = {}
    for scope in (effective, *mappings):
        if isinstance(scope.get("inputs_schema"), list):
            schemas.extend(scope["inputs_schema"])
        if isinstance(scope.get("inputs"), dict):
            merged.update(scope["inputs"])
    ids: set[int] = set()
    for schema in schemas:
        if not isinstance(schema, dict) or schema.get("type") not in ("integration", "integration_multi"):
            continue
        key = schema.get("key")
        entry = merged.get(key) if isinstance(key, str) else None
        if isinstance(entry, dict):
            ids.update(integration_ids_in_value(entry.get("value")))
    return ids


def _referenced_input_keys(value: Any, templating: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_referenced_input_keys(item, templating) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_referenced_input_keys(item, templating) for item in value))
    if not isinstance(value, str):
        return set()
    if templating == "liquid":
        return {dotted or bracketed for dotted, bracketed in _LIQUID_INPUT_REFERENCE.findall(value)}
    try:
        return collect_inputs(parse_string_template(value))
    except Exception:
        # Validation already rejected a template that does not parse, so this is a stored row
        # written before that check. The record then lists no references for it.
        return set()


def _input_references(inputs: Any) -> dict[str, set[str]]:
    if not isinstance(inputs, dict):
        return {}
    references: dict[str, set[str]] = {}
    for key, entry in inputs.items():
        if isinstance(entry, dict):
            if referenced := _referenced_input_keys(entry.get("value"), entry.get("templating")):
                references[key] = referenced
    return references


def _effective_configuration(configuration: dict[str, Any], stored: Optional["HogFunction"]) -> dict[str, Any]:
    # The worker runs `{...storedFunction, ...configuration}`, so a field the request omits runs as stored.
    if stored is None:
        return configuration
    return {
        field: configuration[field] if field in configuration else getattr(stored, field, None)
        for field in _CONTEXT_FIELDS
    }


def sends_real_requests(configuration: dict[str, Any], *, mock_async_functions: bool) -> bool:
    template_id = configuration.get("template_id")
    return not mock_async_functions or (
        isinstance(template_id, str) and template_id.startswith(_UNMOCKED_TEMPLATE_PREFIXES)
    )


def destination_test_run_context(
    configuration: dict[str, Any], *, stored: Optional["HogFunction"], mock_async_functions: bool
) -> HogFunctionTestRunContext:
    effective = _effective_configuration(configuration, stored)
    inputs = effective.get("inputs")
    mappings = [mapping for mapping in effective.get("mappings") or [] if isinstance(mapping, dict)]

    mapping_input_keys: set[str] = set()
    mapping_input_references: dict[str, set[str]] = {}
    for mapping in mappings:
        if isinstance(mapping.get("inputs"), dict):
            mapping_input_keys.update(mapping["inputs"].keys())
        for key, referenced in _input_references(mapping.get("inputs")).items():
            mapping_input_references.setdefault(key, set()).update(referenced)

    return HogFunctionTestRunContext(
        mock_async_functions=mock_async_functions,
        integration_ids=sorted(_integration_ids(effective, mappings)),
        input_keys=sorted(inputs.keys()) if isinstance(inputs, dict) else [],
        mapping_input_keys=sorted(mapping_input_keys),
        input_references={key: sorted(keys) for key, keys in sorted(_input_references(inputs).items())},
        mapping_input_references={key: sorted(keys) for key, keys in sorted(mapping_input_references.items())},
        hog=effective.get("hog"),
    )


def _as_origin(value: str) -> Optional[str]:
    """Reduce a URL to scheme, host and port, so a path, query or userinfo secret never reaches the row."""
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = parts.hostname
    if not scheme or not host:
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS.get(scheme):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, bool):
        return
    elif isinstance(value, int):
        yield str(value)
    elif isinstance(value, float):
        # The worker writes a whole float without its fraction, as JavaScript does.
        yield str(int(value)) if value.is_integer() else str(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_values(item)


def _host_forms(secret: str) -> set[str]:
    # A URL parser lowercases a host and writes a non-ASCII host in punycode, so a secret in a host
    # reaches the origin in those forms.
    forms = {secret.lower()}
    try:
        # UTS 46 without transitional mapping, as the WHATWG URL parser in the worker applies it.
        forms.add(idna.encode(secret, uts46=True, transitional=False).decode("ascii"))
        # The mapped Unicode form, to match inside a decoded punycode label.
        forms.add(idna.uts46_remap(secret, std3_rules=False, transitional=False))
    except idna.IDNAError:
        pass
    return {form for form in forms if form}


# The DNS label limit. The punycode decoder is quadratic in length, and no real label is longer.
_MAX_LABEL_LENGTH = 63


def _decoded_label(label: str) -> str:
    if not label.startswith("xn--") or len(label) > _MAX_LABEL_LENGTH:
        return label
    try:
        return label[4:].encode("ascii").decode("punycode")
    except UnicodeError:
        return label


def _redact_subdomain(origin: str, pattern: Optional[re.Pattern[str]], short_forms: set[str]) -> str:
    # The registrable domain is never redacted. The caller can store any value as a secret, so redacting
    # the domain would let them hide where the requests went.
    parts = _ORIGIN_PARTS.match(origin)
    if parts is None:
        return origin
    scheme, host, port = parts.groups()
    if _is_ip_address(host):
        return origin
    domain = _DOMAIN_PARTS(host)
    subdomain, kept = domain.subdomain, domain.top_domain_under_public_suffix
    if not kept:
        # A host without a public suffix, such as an internal name, keeps only its last label.
        subdomain, _, kept = host.rpartition(".")
    if not subdomain:
        return origin
    if pattern is not None:
        # Punycode encodes a whole label, so a secret inside a longer non-ASCII label shows only once decoded.
        labels = subdomain.split(".")
        decoded = [_decoded_label(label) for label in labels]
        subdomain = ".".join(
            _REDACTED if text != label and pattern.search(text) else label for label, text in zip(labels, decoded)
        )
        subdomain = pattern.sub(_REDACTED, subdomain)
    subdomain = ".".join(_REDACTED if label in short_forms else label for label in subdomain.split("."))
    return f"{scheme}{subdomain}.{kept}{port or ''}"


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def redact_secrets_in_origins(origins: list[str], secrets: Iterable[str]) -> list[str]:
    forms = set().union(*(_host_forms(secret) for secret in secrets))
    if not forms:
        return origins
    long_forms = {form for form in forms if len(form) >= _MIN_SECRET_LENGTH}
    # One pass, longest first, so a secret inside a longer one cannot leave part of the longer one behind.
    pattern = (
        re.compile("|".join(re.escape(form) for form in sorted(long_forms, key=len, reverse=True)), re.IGNORECASE)
        if long_forms
        else None
    )
    return [_redact_subdomain(origin, pattern, forms - long_forms) for origin in origins]


def _stored_secrets(row: ActivityLog, secret_inputs: Any) -> list[str]:
    # Only stored secrets are redacted. A secret the caller submits with the test is under the caller's
    # control, so redacting it would let the caller hide the host they sent requests to.
    context = cast(Detail, row.detail).context
    integration_ids = getattr(context, "integration_ids", None) or []
    configs: list[Any] = []
    if row.team_id is not None and integration_ids:
        records = IntegrationManager.any.with_source_rows().get_many(row.team_id, integration_ids)
        configs = [dict(record.sensitive_config) for record in records.values()]
    return [*_string_values(secret_inputs), *_string_values(configs)]


def without_request_origins(body: Any) -> Any:
    """Drop the reported origins from a worker reply before it goes back to the caller.

    A host can hold a stored secret that the caller must not read back. The audit row keeps the redacted origins.
    """
    if isinstance(body, dict):
        body.pop("request_origins", None)
    return body


def record_test_run_request_origins(
    row: Optional[ActivityLog], response: requests.Response, *, secret_inputs: Any = None
) -> None:
    """Add the origins the worker reports for a test run to the run's `tested` row.

    `secret_inputs` holds the stored secret inputs of the tested function or flow, in any nesting.
    """
    if row is None:
        return
    try:
        body = response.json()
    except ValueError:
        body = None
    origins = body.get("request_origins") if isinstance(body, dict) else None
    if not isinstance(origins, list) or not all(isinstance(origin, str) for origin in origins):
        # The row then cannot say where the requests went, so the gap must be visible.
        TEST_RUN_REQUEST_ORIGINS_MISSING.labels(scope=row.scope).inc()
        logger.warning(
            "test_run.request_origins_missing",
            scope=row.scope,
            team_id=row.team_id,
            item_id=row.item_id,
            activity_log_id=str(row.id),
            status_code=response.status_code,
        )
        return
    # The worker already sends origins. Normalizing again keeps that guarantee in the audit row itself.
    normalized = [origin for origin in (_as_origin(value) for value in origins) if origin is not None]
    redacted = redact_secrets_in_origins(normalized, _stored_secrets(row, secret_inputs))
    update_activity_context(row, request_origins=list(dict.fromkeys(redacted))[:_MAX_REQUEST_ORIGINS])
