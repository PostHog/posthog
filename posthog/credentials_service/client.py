"""Client for the credentials service — platform integration credentials over HTTP.

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
   errored, or the deployment not fully configured means "read `os.environ` as before". That
   covers self-hosted deployments, local development, and the rollout window. It is not an
   outage path: once the client is on and the service is down, the call fails.

   Half-configured (a URL without a signing key, or the reverse) also reads the environment,
   because a deploy that adds one variable before the other must not take down every credential
   read in the pod. It is still a mistake, so it is loud: a warning once per process naming the
   variable to set, and its own `half_configured` reason on the environment fallback counter.

The token carries the request. `keys` is the exact set this call needs, so a token lifted
from a log unlocks those fields for five minutes rather than everything the deployment
may read. There is deliberately no request body.
"""

import os
import time
import functools
from dataclasses import field
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

import requests
import structlog
import posthoganalytics
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.security.outbound_proxy import internal_requests
from posthog.settings.utils import get_list

from .callers import CredentialsCaller
from .errors import CredentialsServiceUnreachableError, SecretInRecoveryError, SecretMissingError

logger = structlog.get_logger(__name__)

RESOLVE_PATH = "/v1/secrets/resolve"
TOKEN_TTL = timedelta(minutes=5)
REQUEST_TIMEOUT_SECONDS = 5

# Rollout gate. Evaluated per call, so it can be turned off without a deploy if the
# service misbehaves. posthoganalytics evaluates locally when a personal API key is
# configured; if that ever stops being true this becomes a network hop on the credential
# path and should move to a settings-only gate.
CREDENTIALS_SERVICE_FLAG = "credentials-service-enabled"
CREDENTIALS_SERVICE_FLAG_DISTINCT_ID = "credentials_service"

CREDENTIALS_SERVICE_FETCH_COUNTER = Counter(
    "posthog_credentials_service_fetch_total",
    "Credential fetches from the credentials service, by outcome",
    labelnames=["outcome"],
)

CREDENTIALS_SERVICE_ENV_FALLBACK_COUNTER = Counter(
    "posthog_credentials_service_env_fallback_total",
    "Credential reads served from the local environment instead of the credentials service",
    labelnames=["reason"],
)

# End to end from the caller's side: signing the token, the round trip, and parsing the body.
# The service's own histogram starts when the request arrives, so it misses connection setup and
# anything slow inside the calling pod.
CREDENTIALS_SERVICE_REQUEST_DURATION = Histogram(
    "posthog_credentials_service_request_duration_seconds",
    "Time a caller spends on one credentials service request, from signing the token to a parsed body",
    labelnames=["caller", "result"],
    buckets=(0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
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


def credentials_service_signing_keys() -> list[str]:
    """The comma-separated `new_key,old_key` set, newest first, whitespace-trimmed.

    Same convention as RECORDING_API_JWT_SECRET: sign with the first. The service accepts
    every key it holds for this deployment, so a key rotation is zero-downtime.
    """
    return [key for key in get_list(settings.CREDENTIALS_SERVICE_JWT_SECRET or "") if key]


def _missing_config() -> str | None:
    """The variable a half-configured deployment still needs, or None.

    Both set, or both unset, are the two states someone can mean. Exactly one is neither.
    """
    has_url = bool(settings.CREDENTIALS_SERVICE_URL)
    has_keys = bool(credentials_service_signing_keys())
    if has_url == has_keys:
        return None
    return "CREDENTIALS_SERVICE_JWT_SECRET" if has_url else "CREDENTIALS_SERVICE_URL"


@functools.cache
def _warn_half_configured(missing: str) -> None:
    logger.warning(
        "credentials_service.half_configured_reading_environment",
        missing=missing,
        detail="Set both CREDENTIALS_SERVICE_URL and CREDENTIALS_SERVICE_JWT_SECRET, or neither.",
    )


def _disabled_reason() -> str | None:
    """Why the environment fallback is in use, or None when the service should be called.

    The flag fails closed: closed means the old environment-variable path, because a flag
    service blip must not take out credential reads. The four reasons matter separately
    during the rollout — "flag_error" is the fail-closed path that quietly keeps a pod on
    environment variables while the flag service is unhealthy, and it must not look like
    a deliberate opt-out.
    """
    missing = _missing_config()
    if missing is not None:
        _warn_half_configured(missing)
        return "half_configured"
    if not settings.CREDENTIALS_SERVICE_URL:
        return "unconfigured"
    try:
        enabled = bool(posthoganalytics.feature_enabled(CREDENTIALS_SERVICE_FLAG, CREDENTIALS_SERVICE_FLAG_DISTINCT_ID))
    except Exception:
        logger.warning("credentials_service.flag_check_failed_defaulting_off", exc_info=True)
        return "flag_error"
    return None if enabled else "flag_off"


def credentials_service_enabled() -> bool:
    """True when the service is configured and the rollout flag is on."""
    return _disabled_reason() is None


def _log_resolve(
    url: str,
    keys: list[str],
    caller: CredentialsCaller,
    started_at_monotonic: float,
    *,
    response: Any = None,
    body: dict[str, Any] | None = None,
    error: BaseException | None = None,
) -> None:
    """One structured line per credential request. Never raises.

    Field names match `data_imports.http.request` (method, url, host, status_code, latency_ms,
    error_class) so a credential read reads alongside the rest of a job's HTTP traffic instead of
    needing its own query. Without it this hop is invisible: a sync that fails on a credential
    shows the source's traffic and a silent gap where the read was.

    What it adds over a plain request log is the part that answers rotation questions — per-key
    `state` and `version_id`. "Which value did this pod actually get, and when did it change?"
    is otherwise unanswerable from the caller's side, because nothing about the value may be
    logged and the service's own audit line lives in a different system.

    Nothing here can carry a credential, and that is a property of what is selected rather than
    of any scrubbing: values are read from the response by name (`state`, `version_id`) and the
    value fields are never among them. The request is logged by URL only — the bearer token is
    in a header that is not touched, and the path carries no parameters.

    Never raises, for the same reason the warehouse observer doesn't: a broken telemetry layer
    must not become a failed credential read.
    """
    try:
        status_code = getattr(response, "status_code", None)
        secrets: dict[str, Any] = (body or {}).get("secrets") or {}
        # `sorted` so two reads of the same keys produce the same line and diff cleanly.
        states = {key: secrets[key].get("state") for key in sorted(secrets)}
        versions = {key: secrets[key].get("version_id") for key in sorted(secrets)}
        missing = sorted((body or {}).get("missing") or [])

        fields: dict[str, Any] = {
            "method": "POST",
            "url": url,
            "host": urlparse(url).hostname or "",
            "status_code": status_code,
            "latency_ms": max(0, int((time.monotonic() - started_at_monotonic) * 1000)),
            "error_class": type(error).__name__ if error is not None else None,
            "caller": str(caller),
            "keys": sorted(keys),
            "states": states,
            "version_ids": versions,
            "missing": missing,
        }

        if error is not None or (status_code is not None and status_code >= 400):
            logger.warning("credentials_service.resolve", **fields)
        elif missing or any(state != "steady" for state in states.values()):
            # A rotating or recovered key, or one the service doesn't hold, is the case worth
            # seeing without turning debug on — it explains a failure, or a value changing under
            # a caller that did nothing differently.
            logger.info("credentials_service.resolve", **fields)
        else:
            # Steady reads are the overwhelming majority and say nothing new, so they sit at
            # debug, the same level the warehouse observer gives an ordinary 2xx.
            logger.debug("credentials_service.resolve", **fields)
    except Exception:
        logger.debug("credentials_service.resolve_log_failed", exc_info=True)


class CredentialsServiceClient:
    def __init__(self, session: requests.Session | None = None) -> None:
        """`session` swaps the transport without changing anything else.

        The default is the shared internal session, which is right for most callers. A product
        that already runs its own instrumented session — warehouse sources meters and logs every
        outbound request through a tracked adapter — passes it here so credential reads land in
        the same place as the rest of that job's HTTP traffic, instead of being the one hop that
        is invisible while you are debugging a sync.

        Anything passed in must have HTTP sample capture switched OFF. Responses on this path
        carry credentials in plaintext, and a sampler that stores request/response bodies for
        later inspection would write them somewhere they must never be.
        """
        self._session = session or internal_requests

    def get(self, key: str, caller: CredentialsCaller) -> str:
        return self.get_many([key], caller)[key]

    def get_many(self, keys: list[str], caller: CredentialsCaller) -> dict[str, str]:
        resolved = self._resolve(keys, caller)
        out: dict[str, str] = {}
        for key in keys:
            secret = resolved[key]
            if secret.state == "recovery" or secret.value is None:
                raise SecretInRecoveryError(key)
            out[key] = secret.value
        return out

    def get_with_incoming(self, key: str, caller: CredentialsCaller) -> RotatingSecret:
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

    def _resolve(self, keys: list[str], caller: CredentialsCaller) -> dict[str, SecretValue]:
        reason = _disabled_reason()
        if reason is not None:
            CREDENTIALS_SERVICE_ENV_FALLBACK_COUNTER.labels(reason=reason).inc()
            return {key: self._from_environment(key, reason) for key in keys}
        return self._fetch(keys, caller)

    def _fetch(self, keys: list[str], caller: CredentialsCaller) -> dict[str, SecretValue]:
        body = self._post(keys, caller)

        missing = set(body.get("missing") or [])
        secrets: dict[str, Any] = body.get("secrets") or {}

        resolved: dict[str, SecretValue] = {}
        for key in keys:
            if key in missing or key not in secrets:
                CREDENTIALS_SERVICE_FETCH_COUNTER.labels(outcome="missing").inc()
                raise SecretMissingError(key)

            payload = secrets[key]
            resolved[key] = SecretValue(
                state=payload.get("state", "steady"),
                value=payload.get("value"),
                incoming=payload.get("incoming"),
            )
            CREDENTIALS_SERVICE_FETCH_COUNTER.labels(outcome="ok").inc()

        return resolved

    def _post(self, keys: list[str], caller: CredentialsCaller) -> dict[str, Any]:
        """The request itself, with every transport failure wearing this client's own type.

        No `requests` exception may escape. Callers sit in the middle of talking to some third
        party, so a bare `HTTPError` from here is indistinguishable from one raised by the API
        they were actually calling — and the difference decides whose problem it is. A misrouted
        `CREDENTIALS_SERVICE_URL` answering 404 is our deploy error, not a dead endpoint of
        theirs, and a caller reading the status code alone cannot tell.
        """
        # Minted outside the try: signing is local work, and a failure there is a bug in this
        # process, not the service being unreachable. Catching it here would file it under the
        # one label nobody investigates.
        started = time.monotonic()
        headers = self._auth_headers(keys, caller)
        url = f"{settings.CREDENTIALS_SERVICE_URL.rstrip('/')}{RESOLVE_PATH}"
        try:
            response = self._session.post(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            # ValueError covers a body that is not JSON. Modern `requests` raises its own
            # JSONDecodeError (a RequestException), but the stdlib/simplejson ValueError still
            # surfaces on older paths, and nothing else in this block raises one.
            body: dict[str, Any] = response.json()
        except (requests.RequestException, ValueError) as e:
            CREDENTIALS_SERVICE_FETCH_COUNTER.labels(outcome="unreachable").inc()
            CREDENTIALS_SERVICE_REQUEST_DURATION.labels(caller=str(caller), result="error").observe(
                time.monotonic() - started
            )
            _log_resolve(url, keys, caller, started, response=getattr(e, "response", None), error=e)
            raise CredentialsServiceUnreachableError(
                f"The credentials service did not answer a credential request: {e}"
            ) from e
        CREDENTIALS_SERVICE_REQUEST_DURATION.labels(caller=str(caller), result="ok").observe(time.monotonic() - started)
        _log_resolve(url, keys, caller, started, response=response, body=body)
        return body

    def _auth_headers(self, keys: list[str], caller: CredentialsCaller) -> dict[str, str]:
        token = encode_jwt(
            {"caller": str(caller), "keys": sorted(set(keys))},
            TOKEN_TTL,
            PosthogJwtAudience.CREDENTIALS_SERVICE,
            signing_key=credentials_service_signing_keys()[0],
        )
        return {"Authorization": f"Bearer {token}"}

    def _from_environment(self, key: str, disabled_reason: str) -> SecretValue:
        value = os.environ.get(key) or getattr(settings, key, "")
        if not value:
            # Carry the reason: without it this reads as "the service doesn't have it", which is
            # the one thing it does not mean — the service was never asked.
            raise SecretMissingError(key, disabled_reason=disabled_reason)
        return SecretValue(state="steady", value=value, incoming=None)


_client = CredentialsServiceClient()


def get(key: str, caller: CredentialsCaller) -> str:
    return _client.get(key, caller)


def get_many(keys: list[str], caller: CredentialsCaller) -> dict[str, str]:
    return _client.get_many(keys, caller)


def get_with_incoming(key: str, caller: CredentialsCaller) -> RotatingSecret:
    return _client.get_with_incoming(key, caller)
