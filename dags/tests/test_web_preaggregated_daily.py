from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4
from unittest.mock import patch, Mock

import dagster
import pytest

from dags.web_preaggregated_daily import (
    pre_aggregate_web_analytics_data,
)
from dags.web_preaggregated_utils import (
    TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
    CLICKHOUSE_SETTINGS,
)


@dataclass
class WebAnalyticsTestData:
    team_id: int
    session_id: str
    person_id: UUID
    event: str
    timestamp: datetime
    properties: dict


def create_pageview_event(
    team_id: int = 1,
    timestamp: datetime | None = None,
    session_id: str | None = None,
    person_id: UUID | None = None,
    pathname: str = "/home",
    utm_source: str = "google",
    host: str = "example.com",
    device_type: str = "Desktop",
    browser: str = "Chrome",
    country_code: str = "US",
    **extra_properties,
) -> WebAnalyticsTestData:
    session_id = session_id or str(uuid4())
    return WebAnalyticsTestData(
        team_id=team_id,
        session_id=session_id,
        person_id=person_id or uuid4(),
        event="$pageview",
        timestamp=timestamp or datetime(2023, 1, 1),
        properties={
            "$pathname": pathname,
            "$host": host,
            "$device_type": device_type,
            "$browser": browser,
            "$geoip_country_code": country_code,
            "$session_id": session_id,
            **extra_properties,
        },
    )


class TestWebAnalyticsPreAggregation:
    @patch("dags.web_preaggregated_internal.sync_execute")
    def test_pre_aggregate_web_analytics_data_with_partition(self, mock_sync_execute):
        context = Mock()
        context.op_config = {
            "team_ids": [1, 2],
            "extra_clickhouse_settings": "max_threads=4",
        }
        context.has_partition_key = True
        context.partition_time_window = (
            datetime(2023, 1, 1),
            datetime(2023, 1, 2),
        )

        def mock_sql_generator(date_start, date_end, team_ids, settings, table_name):
            return f"INSERT INTO {table_name} SELECT * FROM events WHERE date >= '{date_start}' AND date < '{date_end}'"

        pre_aggregate_web_analytics_data(
            context=context,
            table_name="web_stats_daily",
            sql_generator=mock_sql_generator,
        )

        mock_sync_execute.assert_called_once()
        call_args = mock_sync_execute.call_args[0][0]

        assert "INSERT INTO web_stats_daily" in call_args
        assert "date >= '2023-01-01'" in call_args
        assert "date < '2023-01-02'" in call_args

    def test_pre_aggregate_web_analytics_data_no_partition_fails(self):
        context = Mock()
        context.op_config = {}
        context.has_partition_key = False

        def mock_sql_generator(date_start, date_end, team_ids, settings, table_name):
            return "SELECT 1"

        with pytest.raises(dagster.Failure, match="should only be run with a partition key"):
            pre_aggregate_web_analytics_data(
                context=context,
                table_name="web_stats_daily",
                sql_generator=mock_sql_generator,
            )

    def test_clickhouse_settings_integration(self):
        context = Mock()
        context.op_config = {"extra_clickhouse_settings": "max_threads=4"}
        context.has_partition_key = True
        context.partition_time_window = (
            datetime(2023, 1, 1),
            datetime(2023, 1, 2),
        )

        def mock_sql_generator(date_start, date_end, team_ids, settings, table_name):
            for default_key in CLICKHOUSE_SETTINGS:
                assert f"{default_key}=" in settings
            assert "max_threads=4" in settings
            return "SELECT 1"

        with patch("dags.web_preaggregated_internal.sync_execute"):
            pre_aggregate_web_analytics_data(
                context=context,
                table_name="web_stats_daily",
                sql_generator=mock_sql_generator,
            )

    def test_team_ids_defaulting(self):
        context = Mock()
        context.op_config = {}  # No team_ids specified
        context.has_partition_key = True
        context.partition_time_window = (
            datetime(2023, 1, 1),
            datetime(2023, 1, 2),
        )

        def mock_sql_generator(date_start, date_end, team_ids, settings, table_name):
            assert team_ids == TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED
            return "SELECT 1"

        with patch("dags.web_preaggregated_internal.sync_execute"):
            pre_aggregate_web_analytics_data(
                context=context,
                table_name="web_stats_daily",
                sql_generator=mock_sql_generator,
            )

    def test_empty_team_ids_fallback(self):
        context = Mock()
        context.op_config = {"team_ids": []}  # Empty list
        context.has_partition_key = True
        context.partition_time_window = (
            datetime(2023, 1, 1),
            datetime(2023, 1, 2),
        )

        def mock_sql_generator(date_start, date_end, team_ids, settings, table_name):
            assert team_ids == TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED
            return "SELECT 1"

        with patch("dags.web_preaggregated_internal.sync_execute"):
            pre_aggregate_web_analytics_data(
                context=context,
                table_name="web_stats_daily",
                sql_generator=mock_sql_generator,
            )
