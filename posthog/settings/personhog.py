from posthog.settings.utils import get_from_env, str_to_bool

PERSONHOG_ADDR = get_from_env("PERSONHOG_ADDR", "")
PERSONHOG_ENABLED = get_from_env("PERSONHOG_ENABLED", False, type_cast=str_to_bool)
PERSONHOG_TIMEOUT_MS = get_from_env("PERSONHOG_TIMEOUT_MS", 5000, type_cast=int)
PERSONHOG_ROLLOUT_PERCENTAGE = get_from_env("PERSONHOG_ROLLOUT_PERCENTAGE", 0, type_cast=int)
