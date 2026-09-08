"""Kill switches for proactive AI subscription follow-up."""

from posthog.settings.utils import get_from_env, str_to_bool

PULSE_PROACTIVE_ENABLED: bool = get_from_env("PULSE_PROACTIVE_ENABLED", False, type_cast=str_to_bool)
PULSE_PUBLIC_RESEARCH_ENABLED: bool = get_from_env("PULSE_PUBLIC_RESEARCH_ENABLED", False, type_cast=str_to_bool)
# The Temporal activity has a fixed 12-minute safety envelope. Keep the inner deadline below it
# so the Pulse facade always has time to persist a terminal result before activity cancellation.
PULSE_PROACTIVE_TIMEOUT_SECONDS: int = min(
    max(get_from_env("PULSE_PROACTIVE_TIMEOUT_SECONDS", 600, type_cast=int), 0), 600
)
