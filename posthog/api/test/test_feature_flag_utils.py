from posthog.test.base import (
    APIBaseTest,
)
# from posthog.models.cohort.util import get_sorted_cohort_ids


class TestFeatureFlagUtils(APIBaseTest):
    def setUp(self):
        super().setUp()

    def test_cant_create_flag_with_duplicate_key(self):
        pass
