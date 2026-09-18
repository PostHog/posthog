import datetime
from typing import cast
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from posthog.cloud_utils import TEST_clear_instance_license_cache
from posthog.models.organization import Organization
from posthog.tasks.sync_all_organization_available_product_features import (
    SHARD_COUNT,
    sync_all_organization_available_product_features,
)
from posthog.tasks.sync_billing import sync_available_product_features_from_billing

from ee.models.license import License, LicenseManager


@override_settings(CLOUD_DEPLOYMENT="US")
class TestCloudOrganizationFeatureSync(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )
        TEST_clear_instance_license_cache(is_instance_licensed=True, instance_license=license)

    def tearDown(self) -> None:
        TEST_clear_instance_license_cache()
        super().tearDown()

    def _create_organization(self, uuid_int: int, customer_id: str | None) -> Organization:
        return Organization.objects.create(id=UUID(int=uuid_int), name="org", customer_id=customer_id)

    @patch("posthog.tasks.sync_billing.sync_available_product_features_from_billing.delay")
    def test_queues_billing_customers_in_the_current_shard(self, delay_mock: MagicMock) -> None:
        shard = 5
        in_shard = self._create_organization(SHARD_COUNT * 1000 + shard, customer_id="cus_1")
        self._create_organization(SHARD_COUNT * 1001 + shard, customer_id=None)
        self._create_organization(SHARD_COUNT * 1002 + shard + 1, customer_id="cus_2")

        with time_machine.travel(datetime.datetime(2024, 1, 1, shard, 30, tzinfo=datetime.UTC), tick=False):
            sync_all_organization_available_product_features()

        assert {call.args[0] for call in delay_mock.call_args_list} == {str(in_shard.id)}

    @patch("posthog.tasks.sync_billing.sync_available_product_features_from_billing.delay")
    def test_queues_nothing_without_a_billing_license(self, delay_mock: MagicMock) -> None:
        License.objects.all().delete()
        TEST_clear_instance_license_cache()
        self._create_organization(SHARD_COUNT * 1000, customer_id="cus_1")

        sync_all_organization_available_product_features()

        delay_mock.assert_not_called()

    @patch("ee.billing.billing_manager.http_session.get")
    def test_refreshes_the_cached_entitlements_of_one_organization(self, mock_get: MagicMock) -> None:
        organization = self.organization
        organization.available_product_features = [{"key": "surveys", "name": "Surveys"}]
        organization.save()

        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "available_product_features": [{"key": "group_analytics", "name": "Group analytics"}]
        }

        sync_available_product_features_from_billing(str(organization.id))

        organization.refresh_from_db()
        assert organization.available_product_features == [{"key": "group_analytics", "name": "Group analytics"}]
