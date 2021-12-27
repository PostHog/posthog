import pytest

from posthog.test.base import BaseTest

MIGRATION_NAME = "0003_fill_person_distinct_id2"


class Test0003FillPersonDistinctId2(BaseTest):

    # Run the full migration through
    @pytest.mark.ee
    def test_run_migration_in_full(self):
        raise NotImplementedError("todo")
