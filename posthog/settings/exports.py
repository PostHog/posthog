from posthog.settings.utils import get_from_env

BROWSERLESS_CDP_URL: str = get_from_env("BROWSERLESS_CDP_URL", "")
BROWSERLESS_TOKEN: str = get_from_env("BROWSERLESS_TOKEN", "")
BROWSERLESS_SESSION_TIMEOUT_MS: int = get_from_env("BROWSERLESS_SESSION_TIMEOUT_MS", 180000, type_cast=int)
BROWSERLESS_CONNECT_TIMEOUT_MS: int = get_from_env("BROWSERLESS_CONNECT_TIMEOUT_MS", 30000, type_cast=int)

# Seconds the image exporter waits for a rendered asset (page load, content selector, final screenshot).
# Configurable so heavy renders can be given more headroom without a code change.
IMAGE_EXPORTER_RENDER_TIMEOUT_SECONDS: int = get_from_env("IMAGE_EXPORTER_RENDER_TIMEOUT_SECONDS", 40, type_cast=int)
# Dashboards render many tiles (each an .InsightCard) and legitimately take longer to settle, so they
# get a higher budget than a single insight.
IMAGE_EXPORTER_DASHBOARD_RENDER_TIMEOUT_SECONDS: int = get_from_env(
    "IMAGE_EXPORTER_DASHBOARD_RENDER_TIMEOUT_SECONDS", 90, type_cast=int
)
