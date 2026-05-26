from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context


def _captured_settings(mock_pool: MagicMock) -> dict:
    client_mock = mock_pool.return_value.__enter__.return_value
    return client_mock.execute.call_args.kwargs["settings"]


class TestSyncExecuteSettings(SimpleTestCase):
    """Settings-stripping behavior for readonly ClickHouse profiles like BILLING."""

    @parameterized.expand(
        [
            (ClickHouseUser.DEFAULT,),
            (ClickHouseUser.APP,),
            (ClickHouseUser.API,),
            (ClickHouseUser.META,),
        ]
    )
    @patch("posthog.clickhouse.client.execute.get_client_from_pool")
    def test_max_query_size_kept_for_non_readonly_users(
        self, ch_user: ClickHouseUser, mock_get_client: MagicMock
    ) -> None:
        mock_get_client.return_value.__enter__.return_value.execute.return_value = []

        with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.USAGE_REPORT):
            sync_execute("SELECT 1", ch_user=ch_user)

        settings = _captured_settings(mock_get_client)
        assert "max_query_size" in settings

    @patch("posthog.clickhouse.client.execute.get_client_from_pool")
    def test_max_query_size_stripped_for_billing_user(self, mock_get_client: MagicMock) -> None:
        mock_get_client.return_value.__enter__.return_value.execute.return_value = []

        with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.USAGE_REPORT):
            sync_execute("SELECT 1", ch_user=ClickHouseUser.BILLING)

        settings = _captured_settings(mock_get_client)
        assert "max_query_size" not in settings
        # Sanity-check that non-stripped defaults are still present.
        assert settings.get("join_algorithm") == "direct,parallel_hash,hash"

    @patch("posthog.clickhouse.client.execute.get_client_from_pool")
    def test_max_query_size_stripped_when_promoted_to_billing_via_product_tag(
        self, mock_get_client: MagicMock
    ) -> None:
        mock_get_client.return_value.__enter__.return_value.execute.return_value = []

        with tags_context(product=Product.BILLING, feature=Feature.USAGE_REPORT):
            sync_execute("SELECT 1")

        settings = _captured_settings(mock_get_client)
        assert "max_query_size" not in settings

    @patch("posthog.clickhouse.client.execute.get_client_from_pool")
    def test_caller_provided_max_query_size_is_also_stripped_for_billing(
        self, mock_get_client: MagicMock
    ) -> None:
        mock_get_client.return_value.__enter__.return_value.execute.return_value = []

        with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.USAGE_REPORT):
            sync_execute(
                "SELECT 1",
                settings={"max_query_size": 2_000_000, "max_execution_time": 60},
                ch_user=ClickHouseUser.BILLING,
            )

        settings = _captured_settings(mock_get_client)
        assert "max_query_size" not in settings
        assert settings.get("max_execution_time") == 60
