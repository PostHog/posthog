"""Manual registrations for core activity-log configs.

This file has no owner so model teams can register their configs without a review from the
activity-log owners. Keep config merging and validation in the shared activity-log module.
"""

from types import ModuleType

from posthog.models import oauth_activity_log_config
from posthog.models.person import person_activity_log_config

MODULES: tuple[ModuleType, ...] = (
    oauth_activity_log_config,
    person_activity_log_config,
)
