"""The origins an integration's credentials may be sent to, by integration kind, and the integrations
the worker resolves into a function's inputs.

An origin is `scheme://host[:port]` with the default port left out, as `secret_origins.url_origin`
returns it. A kind's origins are either fixed, or the integration's own instance, read from one config
key. Integration config cannot be edited after creation, so it is a trusted anchor.

A kind missing from `INTEGRATION_ORIGINS` is unlisted, and the API treats it like a secret whose
origins are unknown: a save may keep the config it already had, and any other save that sends it
anywhere is refused.
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from posthog.dataclasses import frozen
from posthog.models.integration.oauth import salesforce_instance_host

from products.cdp.backend.secret_origins import url_origin


@frozen
class InstanceOrigin:
    config_key: str
    # The origin of the config value, or None when the value is not an instance this kind may use.
    origin: Callable[[str], str | None]


@frozen
class IntegrationInput:
    key: str
    holds_list: bool
    integration_ids: list[int]


def _https_origin(url: str) -> str | None:
    origin = url_origin(url, True)
    return origin if origin and origin.startswith("https://") else None


INTEGRATION_ORIGINS: dict[str, frozenset[str] | InstanceOrigin] = {
    "apns": frozenset({"https://api.push.apple.com", "https://api.sandbox.push.apple.com"}),
    "clickup": frozenset({"https://api.clickup.com"}),
    "email": frozenset(),
    "firebase": frozenset({"https://fcm.googleapis.com"}),
    "github": frozenset({"https://api.github.com"}),
    # GitLab can be self-hosted, so any HTTPS host the connection was made to is its own.
    "gitlab": InstanceOrigin(config_key="hostname", origin=_https_origin),
    "google-ads": frozenset({"https://googleads.googleapis.com"}),
    "google-cloud-storage": frozenset({"https://storage.googleapis.com"}),
    "google-pubsub": frozenset({"https://pubsub.googleapis.com"}),
    "google-sheets": frozenset({"https://sheets.googleapis.com"}),
    "hubspot": frozenset({"https://api.hubapi.com"}),
    "intercom": frozenset({"https://api.intercom.io", "https://api.eu.intercom.io", "https://api.au.intercom.io"}),
    "linear": frozenset({"https://api.linear.app"}),
    "linkedin-ads": frozenset({"https://api.linkedin.com"}),
    "salesforce": InstanceOrigin(config_key="instance_url", origin=salesforce_instance_host),
    "slack": frozenset({"https://slack.com"}),
    "snapchat": frozenset({"https://tr.snapchat.com"}),
    "twilio": frozenset({"https://api.twilio.com"}),
}


def integration_origins(kind: str, config: Mapping[str, Any]) -> frozenset[str] | None:
    rule = INTEGRATION_ORIGINS.get(kind)
    if rule is None or isinstance(rule, frozenset):
        return rule
    value = config.get(rule.config_key)
    origin = rule.origin(value) if isinstance(value, str) else None
    return frozenset({origin}) if origin else frozenset()


def _integration_ids(value: Any) -> Iterable[int]:
    # An `integration_multi` input holds a list. The `{"integrationId": ...}` form matches
    # integration_usage.py, so a caller can name an id the worker skips but never miss one. The worker
    # takes any JSON number as an id, so `42.0` resolves integration 42.
    if isinstance(value, dict):
        value = value.get("integrationId")
    for candidate in value if isinstance(value, list) else [value]:
        if type(candidate) is int or (type(candidate) is float and candidate.is_integer()):
            yield int(candidate)


def integration_inputs(inputs_schema: Any, inputs: Any, mappings: Any) -> list[IntegrationInput]:
    # Mirrors `loadIntegrationInputs` in nodejs/src/cdp/services/hog-inputs.service.ts. The worker merges
    # the inputs of each mapping, in order, over the top-level inputs, and reads every schema against that
    # merged set. A mapping input can therefore replace the integration that a top-level input names.
    scopes = [{"inputs_schema": inputs_schema, "inputs": inputs}]
    scopes += [mapping for mapping in mappings or [] if isinstance(mapping, dict)]
    schemas: list[Any] = []
    merged: dict[str, Any] = {}
    for scope in scopes:
        if isinstance(scope.get("inputs_schema"), list):
            schemas.extend(scope["inputs_schema"])
        if isinstance(scope.get("inputs"), dict):
            merged.update(scope["inputs"])
    found = []
    for schema in schemas:
        if not isinstance(schema, dict) or schema.get("type") not in ("integration", "integration_multi"):
            continue
        key = schema.get("key")
        if not isinstance(key, str):
            continue
        entry = merged.get(key)
        ids = _integration_ids(entry.get("value") if isinstance(entry, dict) else None)
        found.append(
            IntegrationInput(key=key, holds_list=schema["type"] == "integration_multi", integration_ids=list(ids))
        )
    return found
