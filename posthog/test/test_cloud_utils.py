from datetime import datetime, timedelta

import pytest
from posthog.test.base import BaseTest

from posthog.cloud_utils import TEST_clear_instance_license_cache, get_cached_instance_license

from ee.models.license import License


class TestCloudUtils(BaseTest):
    def setUp(self):
        assert License.objects.count() == 0

    @pytest.mark.ee
    def test_get_cached_instance_license_returns_correctly(self):
        TEST_clear_instance_license_cache()
        assert get_cached_instance_license() is None

    @pytest.mark.ee
    def test_get_cached_instance_license_if_license_exists(self):
        assert get_cached_instance_license() is None
        license = License.objects.create(key="key", plan="cloud", valid_until=datetime.now() + timedelta(days=30))

        TEST_clear_instance_license_cache()
        assert get_cached_instance_license() == license
