"""Client for the integration service — platform integration credentials over HTTP.

These are the OAuth app client ids/secrets and API keys PostHog itself owns, which used
to be injected as environment variables into every pod that might need one. Reading them
over HTTP means rotation happens in one place with no charts PR and no pod restart, and
every read is attributed.

Three behaviours are load-bearing:

1. **No caching, anywhere.** Every call resolves against the service. That makes the
   service a hard dependency on the credential path, which is the deliberate trade: it
   also makes a rotation land immediately, and it is what lets the service decide when an
   old value is safe to retire (a read after activation necessarily returned the new
   value, which is only true if nobody cached it).

2. **A failure is a failure.** With no cache there is no last known good, so an
   unreachable service raises rather than quietly serving something stale. The service
   needs an availability SLO before the environment variables come out.

3. **Environment fallback only when the client is off.** Flag disabled, a flag check that
   errored, or NEITHER variable configured means "read `os.environ` as before". That covers
   self-hosted deployments, local development, and the rollout window. It is not an outage
   path: once the client is on and the service is down, the call fails.

   Half-configured is the exception, and it raises. A URL without a signing key (or the
   reverse) reads as "not configured" and quietly serves credentials from the pod's own
   environment — which looks like success for every key still mounted there and fails only
   for the ones that have actually moved to the service. That is the shape of a rollout that
   appears to work and hasn't started.

The token carries the request. `keys` is the exact set this call needs, so a token lifted
from a log unlocks those fields for five minutes rather than everything the deployment
may read. There is deliberately no request body.
"""

import os
from dataclasses import field
from datetime import timedelta
from typing import Any

from django.conf import settings

import requests
import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.security.outbound_proxy import internal_requests
from posthog.settings.utils import get_list

from .callers import IntegrationCaller
from .errors import (
    IntegrationServiceMisconfiguredError,
    IntegrationServiceUnreachableError,
    SecretInRecoveryError,
    SecretMissingError,
)

logger = structlog.get_logger(__name__)

RESOLVE_PATH = "/v1/secrets/resolve"
TOKEN_TTL = timedelta(minutes=5)
REQUEST_TIMEOUT_SECONDS = 5

# Rollout gate. Evaluated per call, so it can be turned off without a deploy if the
# service misbehaves. posthoganalytics evaluates locally when a personal API key is
# configured; if that ever stops being true this becomes a network hop on the credential
# path and should move to a settings-only gate.
INTEGRATION_SERVICE_FLAG = "integration-service-enabled"
INTEGRATION_SERVICE_FLAG_DISTINCT_ID = "integration_service"

INTEGRATION_SECRET_FETCH_COUNTER = Counter(
    "posthog_integration_secret_fetch_total",
    "Credential fetches from the integration service, by outcome",
    labelnames=["outcome"],
)

INTEGRATION_SECRET_ENV_FALLBACK_COUNTER = Counter(
    "posthog_integration_secret_env_fallback_total",
    "Credential reads served from the local environment instead of the integration service",
    labelnames=["reason"],
)


@frozen
class SecretValue:
    """One credential field as the service resolved it.

    Both values are repr=False: one of these sits in a frame on every traceback raised
    below _fetch, and a repr would put the credential in the log or in Sentry.
    """

    state: str
    value: str | None = field(repr=False)
    incoming: str | None = field(repr=False)


@frozen
class RotatingSecret:
    """The live value plus the staged replacement, so the two cannot be transposed silently.

    `incoming` is the value a rotation has staged and the service already accepts — NOT the
    outgoing one. A rotation stages the replacement in `<KEY>_FALLBACKS` while the live value
    stays put, and completing it moves the staged value across and drops the sibling. So the
    overlap is the staging window: once a rotation completes, the old value stops being served
    and there is nothing to fall back to.
    """

    current: str = field(repr=False)
    incoming: str | None = field(repr=False)


def integration_service_signing_keys() -> list[str]:
    """The comma-separated `new_key,old_key` set, newest first, whitespace-trimmed.

    Same convention as RECORDING_API_JWT_SECRET: sign with the first. The service accepts
    every key it holds for this deployment, so a key rotation is zero-downtime.
    """
    return [key for key in get_list(settings.INTEGRATION_SERVICE_JWT_SECRET or "") if key]


def _missing_config() -> str | None:
    """The variable a half-configured deployment still needs, or None.

    Both set, or both unset, are the two states someone can mean. Exactly one is neither.
    """
    has_url = bool(settings.INTEGRATION_SERVICE_URL)
    has_keys = bool(integration_service_signing_keys())
    if has_url == has_keys:
        return None
    return "INTEGRATION_SERVICE_JWT_SECRET" if has_url else "INTEGRATION_SERVICE_URL"


def _disabled_reason() -> str | None:
    """Why the environment fallback is in use, or None when the service should be called.

    The flag fails closed: closed means the old environment-variable path, because a flag
    service blip must not take out credential reads. The three reasons matter separately
    during the rollout — "flag_error" is the fail-closed path that quietly keeps a pod on
    environment variables while the flag service is unhealthy, and it must not look like
    a deliberate opt-out.
    """
    if not settings.INTEGRATION_SERVICE_URL or not integration_service_signing_keys():
        return "unconfigured"
    try:
        enabled = bool(posthoganalytics.feature_enabled(INTEGRATION_SERVICE_FLAG, INTEGRATION_SERVICE_FLAG_DISTINCT_ID))
    except Exception:
        logger.warning("integration_secrets.flag_check_failed_defaulting_off", exc_info=True)
        return "flag_error"
    return None if enabled else "flag_off"


def integration_service_enabled() -> bool:
    """True when the service is configured and the rollout flag is on."""
    return _disabled_reason() is None


class IntegrationSecretsClient:
    def get(self, key: str, caller: IntegrationCaller) -> str:
        return self.get_many([key], caller)[key]

    def get_many(self, keys: list[str], caller: IntegrationCaller) -> dict[str, str]:
        resolved = self._resolve(keys, caller)
        out: dict[str, str] = {}
        for key in keys:
            secret = resolved[key]
            if secret.state == "recovery" or secret.value is None:
                raise SecretInRecoveryError(key)
            out[key] = secret.value
        return out

    def get_with_incoming(self, key: str, caller: IntegrationCaller) -> RotatingSecret:
        """The live value plus the staged replacement, while a rotation is in flight.

        For callers that can retry against a third party: try current, and on an auth failure
        retry with `incoming` — which is what you want when the credential has already been
        rotated at the provider and the live value no longer works there. Nothing is reported
        back; the service works out for itself when a staged value is safe to promote.
        """
        secret = self._resolve([key], caller)[key]
        if secret.state == "recovery" or secret.value is None:
            raise SecretInRecoveryError(key)
        return RotatingSecret(current=secret.value, incoming=secret.incoming)

    def _resolve(self, keys: list[str], caller: IntegrationCaller) -> dict[str, SecretValue]:
        missing = _missing_config()
        if missing is not None:
            raise IntegrationServiceMisconfiguredError(missing)
        reason = _disabled_reason()
        if reason is not None:
            INTEGRATION_SECRET_ENV_FALLBACK_COUNTER.labels(reason=reason).inc()
            return {key: self._from_environment(key, reason) for key in keys}
        return self._fetch(keys, caller)

    def _fetch(self, keys: list[str], caller: IntegrationCaller) -> dict[str, SecretValue]:
        body = self._post(keys, caller)

        missing = set(body.get("missing") or [])
        secrets: dict[str, Any] = body.get("secrets") or {}

        resolved: dict[str, SecretValue] = {}
        for key in keys:
            if key in missing or key not in secrets:
                INTEGRATION_SECRET_FETCH_COUNTER.labels(outcome="missing").inc()
                raise SecretMissingError(key)

            payload = secrets[key]
            resolved[key] = SecretValue(
                state=payload.get("state", "steady"),
                value=payload.get("value"),
                # `previous` is the wire name for the staged value. It is wrong, and renaming a
                # field both sides read needs a release where each accepts either — so the
                # correction stops at this boundary rather than propagating the wrong idea.
                incoming=payload.get("previous"),
            )
            INTEGRATION_SECRET_FETCH_COUNTER.labels(outcome="ok").inc()

        return resolved

    def _post(self, keys: list[str], caller: IntegrationCaller) -> dict[str, Any]:
        """The request itself, with every transport failure wearing this client's own type.

        No `requests` exception may escape. Callers sit in the middle of talking to some third
        party, so a bare `HTTPError` from here is indistinguishable from one raised by the API
        they were actually calling — and the difference decides whose problem it is. A misrouted
        `INTEGRATION_SERVICE_URL` answering 404 is our deploy error, not a dead endpoint of
        theirs, and a caller reading the status code alone cannot tell.
        """
        # Minted outside the try: signing is local work, and a failure there is a bug in this
        # process, not the service being unreachable. Catching it here would file it under the
        # one label nobody investigates.
        headers = self._auth_headers(keys, caller)
        try:
            response = internal_requests.post(
                f"{settings.INTEGRATION_SERVICE_URL.rstrip('/')}{RESOLVE_PATH}",
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            # ValueError covers a body that is not JSON. Modern `requests` raises its own
            # JSONDecodeError (a RequestException), but the stdlib/simplejson ValueError still
            # surfaces on older paths, and nothing else in this block raises one.
            return response.json()
        except (requests.RequestException, ValueError) as e:
            INTEGRATION_SECRET_FETCH_COUNTER.labels(outcome="unreachable").inc()
            raise IntegrationServiceUnreachableError(
                f"The integration service did not answer a credential request: {e}"
            ) from e

    def _auth_headers(self, keys: list[str], caller: IntegrationCaller) -> dict[str, str]:
        token = encode_jwt(
            {"caller": str(caller), "keys": sorted(set(keys))},
            TOKEN_TTL,
            PosthogJwtAudience.INTEGRATION_SERVICE,
            signing_key=integration_service_signing_keys()[0],
        )
        return {"Authorization": f"Bearer {token}"}

    def _from_environment(self, key: str, disabled_reason: str) -> SecretValue:
        value = os.environ.get(key) or getattr(settings, key, "")
        if not value:
            # Carry the reason: without it this reads as "the service doesn't have it", which is
            # the one thing it does not mean — the service was never asked.
            raise SecretMissingError(key, disabled_reason=disabled_reason)
        return SecretValue(state="steady", value=value, incoming=None)


_client = IntegrationSecretsClient()


def get(key: str, caller: IntegrationCaller) -> str:
    return _client.get(key, caller)


def get_many(keys: list[str], caller: IntegrationCaller) -> dict[str, str]:
    return _client.get_many(keys, caller)


def get_with_incoming(key: str, caller: IntegrationCaller) -> RotatingSecret:
    return _client.get_with_incoming(key, caller)
