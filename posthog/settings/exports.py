import os

from posthog.settings.utils import get_from_env

BROWSERLESS_CDP_URL: str = get_from_env("BROWSERLESS_CDP_URL", "")
BROWSERLESS_TOKEN: str = get_from_env("BROWSERLESS_TOKEN", "")
BROWSERLESS_SESSION_TIMEOUT_MS: int = get_from_env("BROWSERLESS_SESSION_TIMEOUT_MS", 180000, type_cast=int)
BROWSERLESS_CONNECT_TIMEOUT_MS: int = get_from_env("BROWSERLESS_CONNECT_TIMEOUT_MS", 30000, type_cast=int)

# Threads a Temporal worker uses for subscription webhook sends. A send holds its thread for as long
# as the destination keeps the socket alive, so this is what stops one stalled destination from
# starving the deliveries running beside it.
SUBSCRIPTION_WEBHOOK_SEND_MAX_WORKERS: int = get_from_env(
    "SUBSCRIPTION_WEBHOOK_SEND_MAX_WORKERS", min(32, 4 * (os.cpu_count() or 1)), type_cast=int
)
