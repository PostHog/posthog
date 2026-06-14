import os
from collections.abc import Callable
from typing import Any, Optional

from django.core.exceptions import ImproperlyConfigured

from posthog.utils import str_to_bool

__all__ = ["generate_rsa_private_key_pem", "get_from_env", "get_list", "str_to_bool"]


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
