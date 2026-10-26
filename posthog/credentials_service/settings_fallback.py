"""Read a platform credential from the credentials service, falling back per key to settings.

`client.get` is strict: a key the service does not hold raises `SecretMissingError`. That is right
once a key has moved, and wrong while call sites and keys are still on their way into the service.
The functions here are the strict read plus one temporary bridge — a key the service does not hold
is read from settings instead, and every time that happens it is counted.

**Sequencing.** Call sites and keys cannot move at the same instant, and the service is already live
in production — so `_resolve_one` below keeps reading settings for a key that has not reached the
service yet, counting every time it does. That makes the order of the two moves not matter, and
makes "is the rollout finished?" a metric rather than a belief. It is temporary; the removal
condition is on `_resolve_one`.

Reading through here changes nothing until a key is actually moved into the service. With the
service off (self-hosted, local development, the flag disabled) the client reads the same
`os.environ`/settings value the call site read before, so a migrated call site behaves identically.
"""

import os
from collections.abc import Callable

from django.conf import settings

import structlog
from prometheus_client import Counter

from .callers import CredentialsCaller
from .client import CredentialsServiceClient
from .errors import SecretMissingError

logger = structlog.get_logger(__name__)

SettingsLookup = Callable[[str], str | None]

SETTINGS_FALLBACK_COUNTER = Counter(
    "posthog_credentials_service_settings_fallback_total",
    "Platform credential reads the credentials service could not serve, by what happened instead",
    # outcome="settings": the key is still only in settings, so the rollout isn't finished for it.
    # outcome="unset": the credential isn't configured anywhere, which is the normal state of an
    # integration a deployment doesn't use. Separated because only the first is a rollout gap.
    labelnames=["key", "outcome"],
)

_default_client = CredentialsServiceClient()


def from_django_settings(key: str) -> str | None:
    """The value this key had before the service existed, or None."""
    return (os.environ.get(key) or getattr(settings, key, "")) or None


def _resolve_one(
    key: str,
    caller: CredentialsCaller,
    client: CredentialsServiceClient,
    settings_lookup: SettingsLookup,
) -> str:
    """One credential, falling back to settings while the key is still on its way into the service.

    TEMPORARY, and the removal condition is exact: when
    `posthog_credentials_service_settings_fallback_total{outcome="settings"}` has been zero across a
    full cycle of every caller (a warehouse sync cycle, the OAuth refresh sweep), every key has moved
    and this function collapses back to `client.get`.

    It exists because the call sites and the keys cannot move at the same instant. The service is
    already live, so without this, migrating a call site whose key is not in the service yet fails
    every read of that credential the moment it deploys. The same code also runs where the service
    is not configured at all.

    It is not the silent fallback the client refuses to have. That one is dangerous because it
    hides a half-finished rollout behind apparent success; this one names the key, counts it, and
    is the thing you watch to know when the rollout is finished.

    Only a MISSING key falls back, and the two exclusions are the point:

    - A key in **recovery** must not fall back. Recovery means the credential is known-burned; the
      settings copy is the very value that was burned, so serving it would turn the kill switch
      into a no-op — the one failure mode worse than the caller stopping.
    - An **unreachable service** must not fall back. There is no last known good to fall back to,
      and treating an outage as "the key isn't there" would mask it as a rollout gap.
    """
    try:
        return client.get(key, caller)
    except SecretMissingError:
        value = settings_lookup(key)
        if value:
            SETTINGS_FALLBACK_COUNTER.labels(key=key, outcome="settings").inc()
            logger.warning("credentials_service.settings_fallback", key=key, caller=str(caller))
            return value

        # Configured nowhere. Before this migration the call site read `settings.X` and got the
        # empty string its default provides, and an unusable credential surfaced later as a
        # rejection from the vendor or a "not configured" guard. Keep exactly that: this change
        # moves where a credential comes from, and must not also change what happens when there
        # isn't one. Raising here instead would alter behaviour for every deployment that doesn't
        # use a given integration — self-hosted, local development, and every test that never set
        # it — which is a much wider blast radius than the migration itself.
        SETTINGS_FALLBACK_COUNTER.labels(key=key, outcome="unset").inc()
        logger.debug("credentials_service.unset", key=key, caller=str(caller))
        return ""


def get_or_settings(
    key: str,
    caller: CredentialsCaller,
    *,
    client: CredentialsServiceClient | None = None,
    settings_lookup: SettingsLookup = from_django_settings,
) -> str:
    """One PostHog-owned credential, by the name it has in the service and in settings.

    `client` swaps the transport (see `CredentialsServiceClient`). `settings_lookup` is where a key
    the service does not hold is read from instead; the default is the Django setting or
    environment variable of the same name.
    """
    return _resolve_one(key, caller, client or _default_client, settings_lookup)


def get_many_or_settings(
    keys: list[str],
    caller: CredentialsCaller,
    *,
    client: CredentialsServiceClient | None = None,
    settings_lookup: SettingsLookup = from_django_settings,
) -> dict[str, str]:
    """Several at once, in a single request — a caller usually needs an id and a secret together.

    The batch resolves in one request. If any key in it is missing, the batch cannot say which,
    so the keys are re-resolved one at a time to let the fallback above apply per key. That costs
    extra round trips only while a key is mid-migration, and disappears with the fallback.
    """
    resolved_client = client or _default_client
    try:
        return resolved_client.get_many(keys, caller)
    except SecretMissingError:
        return {key: _resolve_one(key, caller, resolved_client, settings_lookup) for key in keys}
