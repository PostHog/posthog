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
    "read_secret_file",
    "secret_env",
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
            "Unset DEBUG."
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


def read_secret_file(key: str) -> Optional[str]:
    """Return the contents of $POSTHOG_SECRETS_DIR/<key> if it exists, else None.

    Secrets can be delivered as files (one file per secret, filename == the env var
    name) instead of environment variables, so they never appear in /proc/<pid>/environ.
    No stripping: the file holds the exact bytes the env var would have carried (same
    External-Secrets source), preserving byte-parity — important for multi-line PEM
    keys/certs. A missing dir or file returns None so callers fall back to os.getenv.
    """
    secrets_dir = os.environ.get("POSTHOG_SECRETS_DIR")
    if not secrets_dir:
        return None
    try:
        with open(os.path.join(secrets_dir, key), encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return None


def secret_env(key: str, default: Any = None) -> Any:
    """os.getenv(key, default), but a file at $POSTHOG_SECRETS_DIR/<key> takes
    precedence. Use this for secrets read outside get_from_env (raw os.getenv sites)."""
    file_value = read_secret_file(key)
    if file_value is not None:
        return file_value
    return os.getenv(key, default)


def get_from_env(
    key: str,
    default: Any = None,
    *,
    optional: bool = False,
    type_cast: Optional[Callable] = None,
) -> Any:
    value = read_secret_file(key)
    if value is None:
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
