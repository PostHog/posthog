"""The origins an integration's credentials may be sent to, by integration kind, and the integrations
the worker resolves into a function's inputs.

An origin is `scheme://host[:port]` with the default port left out, as `secret_origins.url_origin`
returns it. A kind's origins are either fixed, or the integration's own instance, read from one config
key. Integration config cannot be edited after creation, so it is a trusted anchor. A kind can also
name the worker functions that take the connection itself, such as `sendPushNotification`.

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


@frozen
class KindRule:
    origins: frozenset[str] | InstanceOrigin
    # First-party worker functions that take the connection and resolve its credentials themselves. Code
    # that hands the connection to one of them does not choose where the credentials go.
    worker_calls: frozenset[str] = frozenset()


def _fixed(*origins: str) -> KindRule:
    return KindRule(origins=frozenset(origins))


_PUSH_CALLS = frozenset({"sendPushNotification"})

INTEGRATION_ORIGINS: dict[str, KindRule] = {
    "apns": KindRule(
        origins=frozenset({"https://api.push.apple.com", "https://api.sandbox.push.apple.com"}),
        worker_calls=_PUSH_CALLS,
    ),
    "clickup": _fixed("https://api.clickup.com"),
    "email": _fixed(),
    "firebase": KindRule(origins=frozenset({"https://fcm.googleapis.com"}), worker_calls=_PUSH_CALLS),
    "github": _fixed("https://api.github.com"),
    # GitLab can be self-hosted, so any HTTPS host the connection was made to is its own.
    "gitlab": KindRule(origins=InstanceOrigin(config_key="hostname", origin=_https_origin)),
    "google-ads": _fixed("https://googleads.googleapis.com"),
    "google-cloud-storage": _fixed("https://storage.googleapis.com"),
    "google-pubsub": _fixed("https://pubsub.googleapis.com"),
    "google-sheets": _fixed("https://sheets.googleapis.com"),
    "hubspot": _fixed("https://api.hubapi.com"),
    "intercom": _fixed("https://api.intercom.io", "https://api.eu.intercom.io", "https://api.au.intercom.io"),
    "linear": _fixed("https://api.linear.app"),
    "linkedin-ads": _fixed("https://api.linkedin.com"),
    "salesforce": KindRule(origins=InstanceOrigin(config_key="instance_url", origin=salesforce_instance_host)),
    "slack": _fixed("https://slack.com"),
    "snapchat": _fixed("https://tr.snapchat.com"),
    "twilio": _fixed("https://api.twilio.com"),
}


def integration_origins(kind: str, config: Mapping[str, Any]) -> frozenset[str] | None:
    rule = INTEGRATION_ORIGINS.get(kind)
    if rule is None:
        return None
    if isinstance(rule.origins, frozenset):
        return rule.origins
    value = config.get(rule.origins.config_key)
    origin = rule.origins.origin(value) if isinstance(value, str) else None
    return frozenset({origin}) if origin else frozenset()


# The worker resolves `access_token` to a placeholder and adds the raw token as `access_token_raw`.
_CREDENTIAL_FIELDS = frozenset({"access_token", "access_token_raw"})


def public_config(config: Mapping[str, Any], sensitive_config: Mapping[str, Any]) -> dict[str, Any]:
    """The fields of a connection that the worker resolves to their value in its config, which the API
    shows to every member of the team. Code can read or log them without reaching the credentials."""
    return {
        name: value for name, value in config.items() if name not in sensitive_config and name not in _CREDENTIAL_FIELDS
    }


def integration_worker_calls(kind: str) -> frozenset[str]:
    rule = INTEGRATION_ORIGINS.get(kind)
    return rule.worker_calls if rule else frozenset()


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
