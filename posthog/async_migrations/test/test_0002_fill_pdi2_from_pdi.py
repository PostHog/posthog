from typing import Any

import pytest

from posthog.test.base import BaseTest

MIGRATION_NAME = "0002_fill_pdi2_from_pdi"


class Test0002FillPdi2FromPdi(BaseTest):

    # Run the full migration through
    @pytest.mark.ee
    def test_run_migration_in_full(self):
        raise NotImplementedError("todo")