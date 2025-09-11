from posthog.settings.utils import get_from_env

STRIPE_PUBLIC_KEY = get_from_env("STRIPE_PUBLIC_KEY", None, optional=True)
