"""Client for the integration service — platform integration credentials over HTTP.

These are the OAuth app client ids/secrets and API keys PostHog itself owns, which used
to be injected as environment variables into every pod that might need one. Reading them
over HTTP means rotation happens in one place with no charts PR and no pod restart, and
every read is attributed to a caller.

Three behaviours are load-bearing and worth knowing before changing anything here:

1. **Resolve on use, not at import.** A value cached for `max_age_seconds` (set by the
   service, not by us) is the switchover latency during an emergency rotation. Hoisting
   a value into a module constant would put us back where we started.

2. **Last-known-good on failure.** Warehouse syncs and OAuth refreshes now depend on this
   service. A blip must degrade, not fail, so an expired value is served when the service
   is unreachable.

3. **Environment fallback when unconfigured.** This repository is public and self-hosted
   deployments have no such service, so an unset `INTEGRATION_SERVICE_URL` means "read
   `os.environ` exactly as before". It doubles as the local-dev path and the break-glass.

The token carries the request. `keys` is the exact set this call needs, so a token lifted
from a log or a trace unlocks those fields for five minutes rather than everything this
caller is entitled to — there is deliberately no request body.
"""

import os
import time
import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings

import structlog
from prometheus_client import Counter

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.security.outbound_proxy import internal_requests
from posthog.settings.utils import get_list

from .errors import SecretDeniedError, SecretInRecoveryError, SecretMissingError

logger = structlog.get_logger(__name__)

RESOLVE_PATH = "/v1/secrets/resolve"
TOKEN_TTL = timedelta(minutes=5)
REQUEST_TIMEOUT_SECONDS = 5
# Used only when the service omits the hint; the service normally sets it.
DEFAULT_MAX_AGE_SECONDS = 60

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


@dataclass(frozen=True, kw_only=True)
class SecretValue:
    """One credential field as the service resolved it."""

    state: str
    value: str | None
    previous: str | None


@dataclass(frozen=True, kw_only=True)
class _CacheEntry:
    secret: SecretValue
    expires_at: float


def integration_service_signing_keys() -> list[str]:
    """The comma-separated `new_key,old_key` set, newest first, whitespace-trimmed.

    Same convention as RECORDING_API_JWT_SECRET: sign with the first, and the service
    verifies against all of this caller's keys, so rotation is zero-downtime.
    """
    return [key for key in get_list(settings.INTEGRATION_SERVICE_JWT_SECRET or "") if key]


def integration_service_enabled() -> bool:
    """True once both a service URL and a signing key are configured.

    Until then every read falls back to the environment, so the client can ship dormant
    and be enabled per environment.
    """
    return bool(settings.INTEGRATION_SERVICE_URL) and bool(integration_service_signing_keys())


class IntegrationSecretsClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, _CacheEntry] = {}
        # Keys whose last successful third-party call needed the previous value. Reported
        # on the next resolve so a rotation can tell "nobody needs the old value" apart
        # from "nothing is reading this at all" — see the service's usage rollup.
        self._previous_used: set[str] = set()

    # -- public API ---------------------------------------------------------------

    def get(self, key: str) -> str:
        value = self.get_many([key])[key]
        return value

    def get_many(self, keys: list[str]) -> dict[str, str]:
        resolved = self._resolve(keys)
        out: dict[str, str] = {}
        for key in keys:
            secret = resolved[key]
            if secret.state == "recovery" or secret.value is None:
                raise SecretInRecoveryError(key)
            out[key] = secret.value
        return out

    def get_with_previous(self, key: str) -> tuple[str, str | None]:
        """Current value plus the outgoing one while a rotation is in flight.

        For callers that can retry against a third party: try current, and on an auth
        failure retry with previous and call `report_previous_used(key)` so the rotation
        knows the old value is still needed.
        """
        secret = self._resolve([key])[key]
        if secret.state == "recovery" or secret.value is None:
            raise SecretInRecoveryError(key)
        return secret.value, secret.previous

    def report_previous_used(self, key: str) -> None:
        with self._lock:
            self._previous_used.add(key)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    # -- internals ----------------------------------------------------------------

    def _resolve(self, keys: list[str]) -> dict[str, SecretValue]:
        if not integration_service_enabled():
            INTEGRATION_SECRET_ENV_FALLBACK_COUNTER.labels(reason="not_configured").inc()
            return {key: self._from_environment(key) for key in keys}

        now = _monotonic()
        with self._lock:
            fresh = {key: entry.secret for key, entry in self._cache.items() if key in keys and entry.expires_at > now}
        wanted = [key for key in keys if key not in fresh]
        if not wanted:
            INTEGRATION_SECRET_FETCH_COUNTER.labels(outcome="cache_hit").inc()
            return fresh

        try:
            fetched = self._fetch(wanted)
        except Exception as error:
            return {**fresh, **self._degrade(wanted, error)}

        return {**fresh, **fetched}

    def _fetch(self, keys: list[str]) -> dict[str, SecretValue]:
        with self._lock:
            previous_used = sorted(self._previous_used & set(keys))

        response = internal_requests.post(
            f"{settings.INTEGRATION_SERVICE_URL.rstrip('/')}{RESOLVE_PATH}",
            headers=self._auth_headers(keys, previous_used),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()

        with self._lock:
            # The report has been delivered; drop it so it is not counted again.
            self._previous_used -= set(previous_used)

        # Explicit None check, not `or`: 0 is a meaningful value meaning "do not cache
        # this at all", which is how an emergency rotation is driven fleet-wide without
        # redeploying callers. Treating it as falsy would silently keep serving the
        # burned credential for the default TTL.
        raw_max_age = body.get("max_age_seconds")
        max_age = DEFAULT_MAX_AGE_SECONDS if raw_max_age is None else int(raw_max_age)
        expires_at = _monotonic() + max_age
        denied = set(body.get("denied") or [])
        missing = set(body.get("missing") or [])
        secrets: dict[str, Any] = body.get("secrets") or {}

        resolved: dict[str, SecretValue] = {}
        for key in keys:
            if key in denied:
                INTEGRATION_SECRET_FETCH_COUNTER.labels(outcome="denied").inc()
                raise SecretDeniedError(key)
            if key in missing or key not in secrets:
                INTEGRATION_SECRET_FETCH_COUNTER.labels(outcome="missing").inc()
                raise SecretMissingError(key)

            payload = secrets[key]
            secret = SecretValue(
                state=payload.get("state", "steady"),
                value=payload.get("value"),
                previous=payload.get("previous"),
            )
            resolved[key] = secret
            INTEGRATION_SECRET_FETCH_COUNTER.labels(outcome="ok").inc()
            with self._lock:
                self._cache[key] = _CacheEntry(secret=secret, expires_at=expires_at)

        return resolved

    def _auth_headers(self, keys: list[str], previous_used: list[str]) -> dict[str, str]:
        payload: dict[str, Any] = {"caller": settings.INTEGRATION_SERVICE_CALLER, "keys": sorted(keys)}
        if previous_used:
            payload["previous_used"] = previous_used
        token = encode_jwt(
            payload,
            TOKEN_TTL,
            PosthogJwtAudience.INTEGRATION_SERVICE,
            signing_key=integration_service_signing_keys()[0],
        )
        return {"Authorization": f"Bearer {token}"}

    def _degrade(self, keys: list[str], error: Exception) -> dict[str, SecretValue]:
        """Serve the last known good value, or fall back to the environment.

        Deliberately does NOT re-raise for a transport failure: the alternative is that a
        few seconds of integration-service unavailability fails every warehouse sync in
        flight. A denial or a missing key is a different matter and propagates.
        """
        if isinstance(error, SecretDeniedError | SecretMissingError | SecretInRecoveryError):
            raise error

        logger.warning(
            "integration_secrets.fetch_failed",
            keys=sorted(keys),
            error=str(error),
        )
        out: dict[str, SecretValue] = {}
        for key in keys:
            with self._lock:
                stale = self._cache.get(key)
            if stale is not None:
                INTEGRATION_SECRET_FETCH_COUNTER.labels(outcome="stale").inc()
                out[key] = stale.secret
                continue
            INTEGRATION_SECRET_ENV_FALLBACK_COUNTER.labels(reason="service_unavailable").inc()
            out[key] = self._from_environment(key)
        return out

    def _from_environment(self, key: str) -> SecretValue:
        value = os.environ.get(key) or getattr(settings, key, "")
        if not value:
            raise SecretMissingError(key)
        return SecretValue(state="steady", value=value, previous=None)


def _monotonic() -> float:
    return time.monotonic()


_client = IntegrationSecretsClient()


def get(key: str) -> str:
    return _client.get(key)


def get_many(keys: list[str]) -> dict[str, str]:
    return _client.get_many(keys)


def get_with_previous(key: str) -> tuple[str, str | None]:
    return _client.get_with_previous(key)


def report_previous_used(key: str) -> None:
    _client.report_previous_used(key)


def clear_cache() -> None:
    _client.clear_cache()
