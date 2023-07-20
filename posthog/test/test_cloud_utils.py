from datetime import datetime, timedelta

import pytest

from ee.models.license import License
from posthog.cloud_utils import TEST_clear_cloud_cache, is_cloud
from posthog.test.base import BaseTest


class TestCloudUtils(BaseTest):
    def setUp(self):
        assert License.objects.count() == 0

    @pytest.mark.ee
    def test_is_cloud_returns_correctly(self):
        TEST_clear_cloud_cache()
        assert is_cloud() is False

    @pytest.mark.ee
    def test_is_cloud_checks_license(self):
        assert is_cloud() is False
        License.objects.create(key="key", plan="cloud", valid_until=datetime.now() + timedelta(days=30))

        TEST_clear_cloud_cache()
        assert is_cloud()

    @pytest.mark.ee
    def test_is_cloud_caches_result(self):
        TEST_clear_cloud_cache()
        assert not is_cloud()
        assert not is_cloud()

        License.objects.create(key="key", plan="cloud", valid_until=datetime.now() + timedelta(days=30))

        assert not is_cloud()
