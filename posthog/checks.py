"""Core Django system checks, and the ID scheme every PostHog system check follows.

A system check catches a deployment misconfiguration when the process starts (`migrate`, `check`,
`runserver`) instead of in user traffic. Each check ID has the form `posthog.<area>.<level><nnn>`:

- `<area>` names what the check guards, such as `oauth` or `storage`. A product check uses the
  product name, such as `posthog.canvas.E001`.
- `<level>` is `E` for an error, which stops `migrate` and `runserver`, or `W` for a warning,
  which only prints.
- `<nnn>` counts up from 001 inside each area and level. Never reuse a retired number.

Core checks live in this module, grouped by area. A product check lives in its product's
`backend/checks.py` and registers through `register_check` from this module. Declare every ID a
check can emit in `register_check`, so `test_system_check_ids.py` can verify them from Django's
check registry without running the check.
"""

import re
from collections.abc import Callable, Sequence
from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Error, Warning, register

from posthog.oauth_signing_key import oidc_signing_key_configured
from posthog.product_db_router import get_product_db_routes
from posthog.storage.object_storage import is_usable_endpoint

CHECK_ID_PATTERN = re.compile(r"^posthog\.[a-z][a-z0-9_]*\.[EW]\d{3}$")

CheckFunction = Callable[..., list[CheckMessage]]


def register_check(*check_ids: str, tags: Sequence[str] = ()) -> Callable[[CheckFunction], CheckFunction]:
    def decorator(check: CheckFunction) -> CheckFunction:
        setattr(check, "check_ids", check_ids)  # noqa: B010
        return register(*tags)(check)

    return decorator


# OAuth

OAUTH_SIGNING_KEY_MISSING = "posthog.oauth.W001"


@register_check(OAUTH_SIGNING_KEY_MISSING)
def check_oidc_signing_key(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    if oidc_signing_key_configured():
        return []
    return [
        Warning(
            "OIDC_RSA_PRIVATE_KEY is not set, so OAuth clients cannot be created. "
            "MCP clients, dynamic client registration and toolbar sign-in fail with an OAuth server_error.",
            hint="Set OIDC_RSA_PRIVATE_KEY to an RSA private key in PEM format, for example the output of "
            "`openssl genrsa 2048`.",
            id=OAUTH_SIGNING_KEY_MISSING,
        )
    ]


# Object storage

STORAGE_PUBLIC_ENDPOINT_UNUSABLE = "posthog.storage.E001"


@register_check(STORAGE_PUBLIC_ENDPOINT_UNUSABLE)
def check_object_storage_public_endpoint(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    """Catch a misconfigured OBJECT_STORAGE_PUBLIC_ENDPOINT at startup rather than in user traffic.

    An unsubstituted deployment template literal (e.g. `https://${POSTHOG_DOMAIN}`) makes boto3
    raise `ValueError` on client construction, which previously surfaced as 500s on every
    hypercache-backed read. Failing the system check makes the bad rollout obvious immediately.
    """
    errors: list[CheckMessage] = []

    endpoint = settings.OBJECT_STORAGE_PUBLIC_ENDPOINT
    if settings.OBJECT_STORAGE_ENABLED and endpoint and not is_usable_endpoint(endpoint):
        errors.append(
            Error(
                f"OBJECT_STORAGE_PUBLIC_ENDPOINT is not a usable URL: {endpoint!r}",
                hint="Check the deployment env — it likely contains an unsubstituted ${...} template placeholder.",
                id=STORAGE_PUBLIC_ENDPOINT_UNUSABLE,
            )
        )

    return errors


# Field encryption

ENCRYPTION_SALT_KEY_WRONG_LENGTH = "posthog.encryption.E001"


@register_check(ENCRYPTION_SALT_KEY_WRONG_LENGTH)
def check_encryption_salt_keys(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    # Each ENCRYPTION_SALT_KEYS entry is used directly as a Fernet key, which must be exactly 32 bytes.
    # A wrong-length key otherwise fails lazily with an opaque error on the first encrypt/decrypt — and
    # during a SECRET_KEY / ENCRYPTION_SALT_KEYS rotation that surfaces as a confusing runtime crash
    # instead of a clear config error. SECRET_KEY / SALT_KEY are exempt: they run through PBKDF2, which
    # normalizes any input length to 32 bytes.
    errors: list[CheckMessage] = []
    for index, key in enumerate(settings.ENCRYPTION_SALT_KEYS):
        byte_length = len(key.encode("utf-8"))
        if byte_length != 32:
            errors.append(
                Error(
                    f"ENCRYPTION_SALT_KEYS[{index}] must be exactly 32 bytes, got {byte_length}.",
                    hint="Generate one with `openssl rand -hex 16` (produces 32 characters).",
                    id=ENCRYPTION_SALT_KEY_WRONG_LENGTH,
                )
            )
    return errors


# Product database routing

DB_ROUTER_APP_ON_SEVERAL_DATABASES = "posthog.db_router.E001"


@register_check(DB_ROUTER_APP_ON_SEVERAL_DATABASES)
def check_product_db_routes(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    errors: list[CheckMessage] = []

    app_label_to_database: dict[str, str] = {}

    for route in get_product_db_routes():
        existing = app_label_to_database.get(route.app_label)
        if existing is not None and existing != route.database:
            errors.append(
                Error(
                    f"product db route for '{route.app_label}' points to multiple databases",
                    hint="Ensure each product app has exactly one database in db_routing.yaml",
                    id=DB_ROUTER_APP_ON_SEVERAL_DATABASES,
                )
            )
        app_label_to_database[route.app_label] = route.database

    return errors
