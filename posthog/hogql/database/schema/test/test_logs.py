from unittest.mock import Mock

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.database.schema.logs import get_hogql_max_bytes_to_read_for_logs_user_queries


class TestGetHogqlMaxBytesToReadForLogsUserQueries(SimpleTestCase):
    @parameterized.expand(
        [
            ("free", 50_000_000_000),
            ("paid", 150_000_000_000),
            ("enterprise", 150_000_000_000),
        ]
    )
    def test_scales_with_plan_tier(self, tier: str, expected_bytes: int) -> None:
        organization = Mock(get_plan_tier=Mock(return_value=tier))
        assert get_hogql_max_bytes_to_read_for_logs_user_queries(organization) == expected_bytes

    def test_defaults_to_free_tier_when_no_organization(self) -> None:
        assert get_hogql_max_bytes_to_read_for_logs_user_queries(None) == 50_000_000_000
