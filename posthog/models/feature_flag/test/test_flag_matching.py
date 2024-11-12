from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.feature_flag.flag_matching import FeatureFlagMatcher
from posthog.test.base import BaseTest


class TestFlagMatching(BaseTest):
    def test_get_hash(self):
        # Create test flag
        flag = FeatureFlag(key="test-flag", rollout_percentage=50, team=self.team)

        # Test with different identifiers
        matcher1 = FeatureFlagMatcher([flag], "distinct_id_1")
        matcher2 = FeatureFlagMatcher([flag], "distinct_id_2")

        # Same identifier should get same hash
        # distinct_id_1 + test-flag = 0.35140843114131903
        self.assertAlmostEqual(matcher1.get_hash(flag), 0.35140843114131903)
        self.assertAlmostEqual(matcher1.get_hash(flag), 0.35140843114131903)

        # Different identifiers should get different hashes
        # distinct_id_2 + test-flag = 0.34900843133051557
        self.assertAlmostEqual(matcher2.get_hash(flag), 0.34900843133051557)

        # Different salt should produce different hash
        # distinct_id_1 + test-flag + salt = 0.05659409091269017
        self.assertAlmostEqual(matcher1.get_hash(flag, salt="salt"), 0.05659409091269017)

        # Different flag keys should produce different hashes
        flag2 = FeatureFlag(key="different-flag", rollout_percentage=50, team=self.team)
        # distinct_id_1 + different-flag = 0.5078604702829128
        self.assertAlmostEqual(matcher1.get_hash(flag2), 0.5078604702829128)
