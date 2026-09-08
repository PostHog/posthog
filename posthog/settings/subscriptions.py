"""Kill switches for proactive AI subscription follow-up."""

import os

from posthog.settings.utils import get_from_env, get_list, str_to_bool

PULSE_PROACTIVE_ENABLED: bool = get_from_env("PULSE_PROACTIVE_ENABLED", False, type_cast=str_to_bool)
PULSE_PUBLIC_RESEARCH_ENABLED: bool = get_from_env("PULSE_PUBLIC_RESEARCH_ENABLED", False, type_cast=str_to_bool)
# Public repositories are ineligible for staged automation unless explicitly approved.
# Keep the default empty so deployments opt in repository-by-repository.
PULSE_PUBLIC_REPOSITORY_ALLOWLIST: tuple[str, ...] = tuple(get_list(os.getenv("PULSE_PUBLIC_REPOSITORY_ALLOWLIST", "")))
# The Temporal activity has a fixed 12-minute safety envelope. Keep the inner deadline below it
# so the Pulse facade always has time to persist a terminal result before activity cancellation.
PULSE_PROACTIVE_TIMEOUT_SECONDS: int = min(
    max(get_from_env("PULSE_PROACTIVE_TIMEOUT_SECONDS", 600, type_cast=int), 0), 600
)
