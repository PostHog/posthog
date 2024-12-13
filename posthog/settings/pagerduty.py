from posthog.settings.utils import get_from_env

PAGERDUTY_API_KEY = get_from_env("PAGERDUTY_API_KEY", "")
