import os

from posthog.settings.utils import get_list

# These flags will be force-enabled on the frontend
# The features here are released, but the flags are just not yet removed from the code
PERSISTED_FEATURE_FLAGS = get_list(os.getenv("PERSISTED_FEATURE_FLAGS", "")) + [
    "invite-teammates-prompt",
    "insight-legends",
    "multi-dashboard-insights",
]
