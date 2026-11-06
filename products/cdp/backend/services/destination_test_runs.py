"""The activity log record of a hog function test that delivers real requests.

A test with `mock_async_functions` off runs the submitted code with real `fetch` calls and the
credentials of the integrations its inputs name. The record keeps what an investigator needs to
answer who ran which code with which integrations, and never an input value: values can hold
secrets, and the test resolves secret inputs to plaintext before it runs.
"""

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Optional

import requests
import structlog

from posthog.hogql.parser import parse_string_template

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityContextBase, ActivityLog, update_activity_context

from products.cdp.backend.validation import collect_inputs

if TYPE_CHECKING:
    from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)

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


def _integration_ids_in_value(value: Any) -> Iterable[int]:
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
            ids.update(_integration_ids_in_value(entry.get("value")))
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


def record_test_run_request_origins(row: Optional[ActivityLog], response: requests.Response) -> None:
    """Add the origins the worker reports for a test run to the run's `tested` row."""
    if row is None:
        return
    try:
        body = response.json()
    except ValueError:
        body = None
    origins = body.get("request_origins") if isinstance(body, dict) else None
    if not isinstance(origins, list) or not all(isinstance(origin, str) for origin in origins):
        # The row then cannot say where the requests went, so the gap must be visible.
        logger.warning("test_run.request_origins_missing", scope=row.scope, status_code=response.status_code)
        return
    update_activity_context(row, request_origins=origins)
