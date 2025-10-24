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

# Proxy settings
IS_BEHIND_PROXY = get_from_env("IS_BEHIND_PROXY", False, type_cast=str_to_bool)
TRUSTED_PROXIES = os.getenv("TRUSTED_PROXIES", None)
TRUST_ALL_PROXIES = os.getenv("TRUST_ALL_PROXIES", False)


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

# Debug setting to log in as a specific user. Especially useful for connecting to prod from local dev
DEBUG_LOG_IN_AS_EMAIL: str | None = os.getenv("DEBUG_LOG_IN_AS_EMAIL")

if not DEBUG and not TEST and not STATIC_COLLECTION and SECRET_KEY == DEFAULT_SECRET_KEY:
    logger.critical(
        """
You are using the default SECRET_KEY in a production environment!
For the safety of your instance, you must generate and set a unique key.
"""
    )
    sys.exit("[ERROR] Default SECRET_KEY in production. Stopping Django server…\n")

# These are legacy values only kept around for backwards compatibility with self hosted versions
SALT_KEY = get_list(os.getenv("SALT_KEY", "0123456789abcdefghijklmnopqrstuvwxyz"))
# We provide a default as it is needed for hobby deployments
ENCRYPTION_SALT_KEYS = get_list(os.getenv("ENCRYPTION_SALT_KEYS", "00beef0000beef0000beef0000beef00"))

INTERNAL_IPS = ["127.0.0.1", "172.18.0.1"]  # Docker IP
if os.getenv("CORS_ALLOWED_ORIGINS", False):
    CORS_ORIGIN_ALLOW_ALL = False
    CORS_ALLOWED_ORIGINS = get_list(os.getenv("CORS_ALLOWED_ORIGINS", ""))
else:
    CORS_ORIGIN_ALLOW_ALL = True

BLOCKED_GEOIP_REGIONS = get_list(os.getenv("BLOCKED_GEOIP_REGIONS", ""))
