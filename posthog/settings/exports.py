from posthog.settings.utils import get_from_env

BROWSERLESS_CDP_URL: str = get_from_env("BROWSERLESS_CDP_URL", "")
BROWSERLESS_TOKEN: str = get_from_env("BROWSERLESS_TOKEN", "")
BROWSERLESS_SESSION_TIMEOUT_MS: int = get_from_env("BROWSERLESS_SESSION_TIMEOUT_MS", 180000, type_cast=int)
BROWSERLESS_CONNECT_TIMEOUT_MS: int = get_from_env("BROWSERLESS_CONNECT_TIMEOUT_MS", 30000, type_cast=int)
