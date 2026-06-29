# Settings which restrict access to the site across the app
import os
import sys

import structlog

from posthog.settings.base_variables import DEBUG, STATIC_COLLECTION, TEST
from posthog.settings.utils import get_from_env, get_list, str_to_bool

logger = structlog.get_logger(__name__)

# SSL & cookie defaults
if os.getenv("SECURE_COOKIES", None) is None:
    # Default to True if in production
    secure_cookies = not DEBUG and not TEST
else:
    secure_cookies = get_from_env("SECURE_COOKIES", True, type_cast=str_to_bool)

TOOLBAR_COOKIE_SECURE = secure_cookies
SESSION_COOKIE_SECURE = secure_cookies
CSRF_COOKIE_SECURE = secure_cookies
SECURE_SSL_REDIRECT = secure_cookies
SECURE_REDIRECT_EXEMPT = [r"^_health/?"]
SECURE_REFERRER_POLICY = get_from_env("SECURE_REFERRER_POLICY", "same-origin")

if get_from_env("DISABLE_SECURE_SSL_REDIRECT", False, type_cast=str_to_bool):
    SECURE_SSL_REDIRECT = False

raw_site_url = os.getenv("SITE_URL")
CSRF_TRUSTED_ORIGINS = (
    [raw_site_url.rstrip("/")]
    if raw_site_url
    else ["http://localhost:8000", "http://localhost:8010"]  # 8000 is just Django, 8010 is Django + Capture via Caddy
)
CSRF_TRUSTED_ORIGINS += get_list(os.getenv("EXTRA_CSRF_TRUSTED_ORIGINS", ""))
# Proxy settings
IS_BEHIND_PROXY = get_from_env("IS_BEHIND_PROXY", False, type_cast=str_to_bool)
TRUSTED_PROXIES = os.getenv("TRUSTED_PROXIES", None)
TRUST_ALL_PROXIES = get_from_env("TRUST_ALL_PROXIES", False, type_cast=str_to_bool)


if IS_BEHIND_PROXY:
    USE_X_FORWARDED_HOST = True
    USE_X_FORWARDED_PORT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    if not TRUST_ALL_PROXIES and not TRUSTED_PROXIES:
        logger.warning(
            """
                You indicated your instance is behind a proxy (IS_BEHIND_PROXY env var),
                but you haven't configured any trusted proxies. See
                https://posthog.com/docs/configuring-posthog/running-behind-proxy for details.
            """
        )

# IP Block settings
ALLOWED_IP_BLOCKS = get_list(os.getenv("ALLOWED_IP_BLOCKS", ""))
ALLOWED_HOSTS = get_list(os.getenv("ALLOWED_HOSTS", "*"))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.2/howto/deployment/checklist/

DEFAULT_SECRET_KEY = "<randomly generated secret key>"

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY: str = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)

SECRET_KEY_FALLBACKS: list[str] = get_list(os.getenv("SECRET_KEY_FALLBACKS", ""))

# Dedicated key for signing PostHog-issued JWTs (posthog.jwt), so JWT signing can move off
# SECRET_KEY. Defaults to SECRET_KEY, so deployments keep working until they provision a
# separate key; once set, add the old key to JWT_SIGNING_KEY_FALLBACKS so tokens already in
# flight keep validating until they expire. An empty value coalesces back to SECRET_KEY —
# signing with an empty key is never a valid intent.
JWT_SIGNING_KEY: str = os.getenv("JWT_SIGNING_KEY", "") or SECRET_KEY
# Previous JWT signing keys still trusted for verifying tokens in flight, newest first.
# Defaults to SECRET_KEY_FALLBACKS only when *unset*; an explicit empty value (e.g.
# JWT_SIGNING_KEY_FALLBACKS="") clears it, so operators can stop trusting old JWT keys
# without disturbing SECRET_KEY_FALLBACKS (which Django also uses for session/CSRF rotation).
JWT_SIGNING_KEY_FALLBACKS: list[str] = (
    get_list(os.environ["JWT_SIGNING_KEY_FALLBACKS"])
    if "JWT_SIGNING_KEY_FALLBACKS" in os.environ
    else (SECRET_KEY_FALLBACKS if JWT_SIGNING_KEY == SECRET_KEY else [])
)


if not DEBUG and not TEST and not STATIC_COLLECTION and SECRET_KEY == DEFAULT_SECRET_KEY:
    logger.critical(
        """
You are using the default SECRET_KEY in a production environment!
For the safety of your instance, you must generate and set a unique key.
"""
    )
    sys.exit("[ERROR] Default SECRET_KEY in production. Stopping Django server…\n")

# RS256 private key for sandbox JWT authentication
# Used to sign tokens; public key is derived from this and injected into sandboxes for verification
SANDBOX_JWT_PRIVATE_KEY: str | None = os.getenv("SANDBOX_JWT_PRIVATE_KEY")
# Verify-only services (e.g. the agent-proxy) set just the public key so they never hold the private
# key. Django leaves this unset and derives the public key from the private key (it mints tokens).
SANDBOX_JWT_PUBLIC_KEY: str | None = os.getenv("SANDBOX_JWT_PUBLIC_KEY")

# Additional RS256 private key accepted during key rotation of SANDBOX_JWT_PRIVATE_KEY
SANDBOX_JWT_PRIVATE_KEY_SECONDARY: str | None = os.getenv("SANDBOX_JWT_PRIVATE_KEY_SECONDARY")
# Additional public key a verify-only service (the agent-proxy) trusts during key rotation, so a token
# signed with either the primary or the secondary key verifies. The proxy holds public keys only.
SANDBOX_JWT_PUBLIC_KEY_SECONDARY: str | None = os.getenv("SANDBOX_JWT_PUBLIC_KEY_SECONDARY")

# Local dev shares one .env with the agent-proxy, which sets the verify-only public keys. Tests must
# stay hermetic: they mint with an overridden private key and verify against the same registry, not
# against whatever key the ambient environment carries.
if TEST:
    SANDBOX_JWT_PUBLIC_KEY = None
    SANDBOX_JWT_PUBLIC_KEY_SECONDARY = None

# Browser origins allowed to read the live stream from the standalone agent-proxy (cross-origin CORS).
# Comma-separated; "*" allows any; empty disables CORS (same-origin path-routing needs none). Only the
# agent-proxy reads this; the Django app ignores it.
TASKS_AGENT_PROXY_CORS_ORIGINS: list[str] = [
    origin.strip() for origin in os.getenv("TASKS_AGENT_PROXY_CORS_ORIGINS", "").split(",") if origin.strip()
]

# Base URL the sandbox agent POSTs its event-ingest stream to. When set (and sequenced ingest is on),
# the run routes ingest to the standalone agent-proxy instead of the Django ASGI short-circuit; unset
# falls back to the Django app URL. Reversible by clearing the env var. Locally: http://localhost:8003
TASKS_AGENT_PROXY_INGEST_URL: str | None = os.getenv("TASKS_AGENT_PROXY_INGEST_URL") or None

# Browser-facing base URL of the agent-proxy for the live-stream read leg, per environment (e.g.
# https://agent-proxy.us.posthog.com). The stream_token endpoint returns it to clients only when this
# is set AND the read-via-proxy flag is enabled for the user; unset means clients read from Django.
TASKS_AGENT_PROXY_PUBLIC_URL: str | None = os.getenv("TASKS_AGENT_PROXY_PUBLIC_URL") or None

# Shared service-to-service secret proving a call to the agent-proxy side-effect callback came from the
# agent-proxy and not directly from a sandbox (which also holds the event-ingest JWT). When set, the
# callback requires a matching X-Agent-Proxy-Secret header. Provision the same value to Django and the
# agent-proxy in production; unset (local/CI) disables the check.
AGENT_PROXY_CALLBACK_SECRET: str | None = os.getenv("AGENT_PROXY_CALLBACK_SECRET") or None

# These are legacy values only kept around for backwards compatibility with self hosted versions
SALT_KEY = get_list(os.getenv("SALT_KEY", "0123456789abcdefghijklmnopqrstuvwxyz"))
# We provide a default as it is needed for hobby deployments. Each entry must be exactly 32 bytes
# (used directly as a Fernet key) — enforced by check_encryption_salt_keys in encrypted_fields.py.
ENCRYPTION_SALT_KEYS = get_list(os.getenv("ENCRYPTION_SALT_KEYS", "00beef0000beef0000beef0000beef00"))

INTERNAL_IPS = ["127.0.0.1", "172.18.0.1"]  # Docker IP
if os.getenv("CORS_ALLOWED_ORIGINS", False):
    CORS_ORIGIN_ALLOW_ALL = False
    CORS_ALLOWED_ORIGINS = get_list(os.getenv("CORS_ALLOWED_ORIGINS", ""))
else:
    CORS_ORIGIN_ALLOW_ALL = True

BLOCKED_GEOIP_REGIONS = get_list(os.getenv("BLOCKED_GEOIP_REGIONS", ""))

# SSRF protection: in dev/DEBUG, is_url_allowed() short-circuits and allows every URL so local
# development can reach localhost services. Set this to run the production validation path in dev —
# e.g. to reproduce or test SSRF fixes — without flipping DEBUG globally.
FORCE_URL_VALIDATION: bool = get_from_env("POSTHOG_FORCE_URL_VALIDATION", False, type_cast=str_to_bool)
