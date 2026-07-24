from posthog.settings.utils import get_from_env

BROWSERLESS_CDP_URL: str = get_from_env("BROWSERLESS_CDP_URL", "")
BROWSERLESS_TOKEN: str = get_from_env("BROWSERLESS_TOKEN", "")
BROWSERLESS_SESSION_TIMEOUT_MS: int = get_from_env("BROWSERLESS_SESSION_TIMEOUT_MS", 180000, type_cast=int)
BROWSERLESS_CONNECT_TIMEOUT_MS: int = get_from_env("BROWSERLESS_CONNECT_TIMEOUT_MS", 30000, type_cast=int)
# Browserless intermittently drops the CDP connection or closes the page/browser mid-render.
# These are transient, so retry the render in-process on a fresh connection before falling back
# to the (much slower) Temporal activity retry. Total render attempts per activity run.
BROWSERLESS_RENDER_MAX_ATTEMPTS: int = get_from_env("BROWSERLESS_RENDER_MAX_ATTEMPTS", 3, type_cast=int)
BROWSERLESS_RENDER_RETRY_BACKOFF_MS: int = get_from_env("BROWSERLESS_RENDER_RETRY_BACKOFF_MS", 1000, type_cast=int)
