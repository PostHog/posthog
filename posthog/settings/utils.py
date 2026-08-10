import os
from collections.abc import Callable
from typing import Any, Optional

from django.core.exceptions import ImproperlyConfigured

from posthog.utils import str_to_bool

__all__ = [
    "assert_debug_not_in_production",
    "generate_rsa_private_key_pem",
    "get_from_env",
    "get_list",
    "resolve_clickhouse_database",
    "str_to_bool",
]


def assert_debug_not_in_production(*, debug: bool, cloud_deployment: Optional[str], test: bool) -> None:
    """Refuse to boot with DEBUG enabled on a deployed cloud environment (US/EU/DEV).

    DEBUG relaxes authentication (e.g. the dev OAuth login bypass in posthog/views.py) and exposes
    debugging surfaces, so it must never run on PostHog Cloud US/EU or the hosted dev/staging env.
    TEST is excluded because the suite runs with DEBUG=1 (see posthog/settings/overrides.py). E2E is
    not listed: it runs only in automated tests and never sets DEBUG, so the guard can't fire there.
    """
    if debug and not test and (cloud_deployment or "").upper() in ("US", "EU", "DEV"):
        raise ImproperlyConfigured(
            f"DEBUG must not be enabled on deployed cloud environments (CLOUD_DEPLOYMENT={cloud_deployment!r}). "
            "Unset DEBUG. Developing cloud-only features locally? Use CLOUD_DEPLOYMENT=E2E instead — "
            "is_cloud() treats it as cloud and it is allowed with DEBUG. "
            "(DEBUG=1 is injected by the flox env: .flox/env/manifest.toml [vars].)"
        )


def generate_rsa_private_key_pem() -> str:
    """Generate an ephemeral RSA private key in PEM format. Used to self-provision
    OIDC_RSA_PRIVATE_KEY in test runs that don't get one from the environment."""
    # Keeps cryptography off the settings import path outside of test runs.
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: PLC0415

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


def resolve_clickhouse_database(
    *,
    env_value: Optional[str],
    test: bool,
    test_db: str,
    is_collect_static: bool,
) -> str:
    """Resolve which ClickHouse database PostHog connects to, and fail loudly when it is unset.

    HogQL prints table names without a database prefix, so the connection's database decides where
    every query resolves. A silent fallback to the "default" database (which holds no PostHog tables)
    turns a config mistake into a confusing "table does not exist" error at query time, so raise here.
    """
    if test:
        return test_db
    if env_value:
        return env_value
    if is_collect_static:
        # collectstatic runs during the image build with no runtime env and never queries ClickHouse.
        return "default"
    raise ImproperlyConfigured(
        "CLICKHOUSE_DATABASE is not set. Set it to the ClickHouse database that holds your PostHog "
        "tables. The dev stack and self-hosted deployments use 'posthog'."
    )


def get_from_env(
    key: str,
    default: Any = None,
    *,
    optional: bool = False,
    type_cast: Optional[Callable] = None,
) -> Any:
    value = os.getenv(key)
    if value is None or value == "":
        if optional:
            return None
        if default is not None:
            return default
        else:
            raise ImproperlyConfigured(f'The environment variable "{key}" is required to run PostHog!')
    if type_cast is not None:
        return type_cast(value)
    return value


def get_list(text: str) -> list[str]:
    if not text:
        return []
    return [item.strip() for item in text.split(",")]


def get_set(text: str) -> set[str]:
    if not text:
        return set()
    return {item.strip() for item in text.split(",")}
