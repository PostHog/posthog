"""Feature-flag re-export.

Lets core code (the HogQL database builder) check the product flag without pulling the facade's
heavier logic surface onto its import path.
"""

from ..logic.flags import (
    DATA_QUALITY_CHECKS_FEATURE_FLAG,
    is_data_quality_checks_enabled,
    is_data_quality_checks_enabled_for_team_id,
)

__all__ = [
    "DATA_QUALITY_CHECKS_FEATURE_FLAG",
    "is_data_quality_checks_enabled",
    "is_data_quality_checks_enabled_for_team_id",
]
