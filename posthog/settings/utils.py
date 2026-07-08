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
    "load_or_mint_dev_oidc_rsa_key",
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


def load_or_mint_dev_oidc_rsa_key() -> str:
    """Return a persistent RSA private key for local dev OIDC signing.

    First launch mints an ephemeral key and writes it to disk; subsequent Django
    restarts read the same key back. Keeps client OAuth sessions valid across
    dev-server reloads. Path defaults to <real-home>/.posthog-dev/oidc-rsa.pem
    (dedicated dir; doesn't collide with the CLI's ~/.posthog/). Override with
    DEV_OIDC_RSA_KEY_PATH.

    Resolves the real home via `pwd.getpwuid(os.getuid())` rather than `HOME`,
    since some launchers (debugpy from IDE debug sessions, sandboxed dev-server
    supervisors) don't propagate HOME to the child process and `Path.expanduser`
    would resolve `~` to the wrong place — silently minting a fresh key every
    restart.

    Any I/O failure (unwriteable path, weird ACL, race with a sibling worker)
    falls back to an ephemeral key with a stderr warning. That trades OAuth
    session stability for keeping Django bootable — the alternative is a
    crash-loop that blocks all local dev.
    """
    import pwd  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    override = os.getenv("DEV_OIDC_RSA_KEY_PATH")
    if override:
        path = Path(override).expanduser()
    else:
        home = pwd.getpwuid(os.getuid()).pw_dir
        path = Path(home) / ".posthog-dev" / "oidc-rsa.pem"
    try:
        if path.is_file():
            return path.read_text()
    except OSError:
        # Unreadable path (perms, symlink loop) — fall through to mint + write.
        pass
    pem = generate_rsa_private_key_pem()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pem)
        path.chmod(0o600)
    except OSError as e:
        # Never crash-loop Django on a dev-only convenience: log to stderr and
        # return the ephemeral key. OAuth sessions may rotate on the next
        # restart until the user fixes the path.
        print(  # noqa: T201
            f"[settings] WARNING: could not persist dev OIDC key to {path}: {e}. "
            f"Falling back to ephemeral — client OAuth sessions will invalidate on Django restart.",
        )
    return pem


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
