from posthog.settings.utils import get_from_env

ANTHROPIC_API_KEY = get_from_env("ANTHROPIC_API_KEY", "")
