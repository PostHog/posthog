import json

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.global_rate_limit_threshold_config import (
    CUSTOM_THRESHOLDS_REDIS_KEY,
    MAX_DISTINCT_ID_CHARS,
    GlobalRateLimitThresholdConfig,
)
from posthog.redis import get_client
from posthog.settings import PLUGINS_RELOAD_REDIS_URL


class TestGlobalRateLimitThresholdConfig(BaseTest):
    def setUp(self):
        super().setUp()
        self.redis_client = get_client(PLUGINS_RELOAD_REDIS_URL)
        self.redis_client.delete(CUSTOM_THRESHOLDS_REDIS_KEY)

    def _blob(self) -> dict:
        raw = self.redis_client.get(CUSTOM_THRESHOLDS_REDIS_KEY)
        return json.loads(raw) if raw is not None else {}

    @parameterized.expand(
        [
            ("token_only", "phc_abc", "", "phc_abc"),
            ("token_and_distinct_id", "phc_abc", "noisy_user", "phc_abc:noisy_user"),
        ]
    )
    def test_resolved_key_format(self, _name, token, distinct_id, expected):
        config = GlobalRateLimitThresholdConfig(token=token, distinct_id=distinct_id, threshold=10)
        self.assertEqual(config.resolved_key, expected)

    def test_resolved_key_truncates_long_distinct_id(self):
        long_distinct_id = "d" * (MAX_DISTINCT_ID_CHARS + 50)
        config = GlobalRateLimitThresholdConfig(token="phc_abc", distinct_id=long_distinct_id, threshold=10)
        self.assertEqual(config.resolved_key, f"phc_abc:{'d' * MAX_DISTINCT_ID_CHARS}")

    def test_post_save_writes_blob(self):
        GlobalRateLimitThresholdConfig.objects.create(token="phc_abc", threshold=1000)
        GlobalRateLimitThresholdConfig.objects.create(token="phc_abc", distinct_id="noisy_user", threshold=50)

        self.assertEqual(self._blob(), {"phc_abc": 1000, "phc_abc:noisy_user": 50})

    def test_update_threshold_updates_blob(self):
        config = GlobalRateLimitThresholdConfig.objects.create(token="phc_abc", threshold=1000)
        self.assertEqual(self._blob(), {"phc_abc": 1000})

        config.threshold = 25
        config.save()
        self.assertEqual(self._blob(), {"phc_abc": 25})

    def test_delete_regenerates_blob(self):
        config = GlobalRateLimitThresholdConfig.objects.create(token="phc_abc", threshold=1000)
        GlobalRateLimitThresholdConfig.objects.create(token="phc_xyz", threshold=2000)

        config.delete()
        self.assertEqual(self._blob(), {"phc_xyz": 2000})

    def test_delete_last_row_removes_key(self):
        config = GlobalRateLimitThresholdConfig.objects.create(token="phc_abc", threshold=1000)
        self.assertIsNotNone(self.redis_client.get(CUSTOM_THRESHOLDS_REDIS_KEY))

        config.delete()
        self.assertIsNone(self.redis_client.get(CUSTOM_THRESHOLDS_REDIS_KEY))
