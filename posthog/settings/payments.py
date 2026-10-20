from posthog.settings.utils import get_from_env

STRIPE_PUBLIC_KEY = get_from_env("STRIPE_PUBLIC_KEY", None, optional=True)
USAGE_COUNTER_REALTIME_MODES = get_from_env("USAGE_COUNTER_REALTIME_MODES", "")
