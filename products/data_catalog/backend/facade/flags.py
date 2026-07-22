"""Feature-flag re-export.

Lets core code (the HogQL database builder) check the product flag without pulling the
facade's heavier logic surface (query runners, execution) onto its import path.
"""

from ..logic.flags import DATA_CATALOG_FEATURE_FLAG, is_data_catalog_enabled

__all__ = ["DATA_CATALOG_FEATURE_FLAG", "is_data_catalog_enabled"]
