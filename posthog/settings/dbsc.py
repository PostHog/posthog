from posthog.settings.base_variables import DEBUG, TEST
from posthog.settings.utils import get_from_env, get_list, str_to_bool

# Off in the test suite, like SESSION_RISK_ENABLED, so the per-request flag check runs only in tests that enable it.
DBSC_ENABLED: bool = get_from_env("DBSC_ENABLED", not TEST, type_cast=str_to_bool)

# Comma-separated, newest first. Empty turns DBSC off instead of falling back to SECRET_KEY.
DBSC_COOKIE_SIGNING_KEYS: list[str] = [
    key
    for key in get_list(get_from_env("DBSC_COOKIE_SIGNING_KEYS", "local-dev-dbsc-cookie" if DEBUG or TEST else ""))
    if key
]
