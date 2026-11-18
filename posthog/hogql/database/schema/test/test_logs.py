import json
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import Mock

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.database.schema.logs import get_hogql_max_bytes_to_read_for_logs_user_queries
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute


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


class TestLogsTrafficClassification(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            (
                "crawler",
                {"user_agent.original": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
                True,
                "Googlebot",
                "Bot",
            ),
            (
                "browser",
                {
                    "user_agent.original": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                },
                False,
                "",
                "Regular",
            ),
            ("no_user_agent", {"vercel.source": "lambda"}, None, None, None),
        ]
    )
    def test_classifies_log_lines_by_user_agent(
        self,
        _name: str,
        attributes: dict[str, str],
        is_bot: bool | None,
        bot_name: str | None,
        traffic_type: str | None,
    ) -> None:
        row = {
            "uuid": "log-1",
            "team_id": self.team.pk,
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "body": "GET / 200",
            "severity_text": "info",
            "severity_number": 9,
            "service_name": "web",
            "resource_attributes": {},
            "attributes_map_str": {f"{key}__str": value for key, value in attributes.items()},
        }
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + json.dumps(row))

        response = execute_hogql_query(
            "SELECT $virt_is_bot, $virt_bot_name, $virt_traffic_type FROM logs WHERE uuid = 'log-1'", team=self.team
        )

        assert response.results == [(is_bot, bot_name, traffic_type)]

    def test_select_star_skips_the_classification_fields(self) -> None:
        response = execute_hogql_query("SELECT * FROM logs LIMIT 1", team=self.team)

        assert not any(column.startswith("$virt_") for column in response.columns or [])
