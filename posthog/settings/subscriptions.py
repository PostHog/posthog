"""Kill switches for proactive AI subscription follow-up."""

from posthog.settings.utils import get_from_env, str_to_bool

PULSE_PROACTIVE_ENABLED: bool = get_from_env("PULSE_PROACTIVE_ENABLED", False, type_cast=str_to_bool)
PULSE_PUBLIC_RESEARCH_ENABLED: bool = get_from_env("PULSE_PUBLIC_RESEARCH_ENABLED", False, type_cast=str_to_bool)
