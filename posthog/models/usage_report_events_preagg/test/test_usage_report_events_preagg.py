from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from django.test import override_settings

from posthog.models.usage_report_events_preagg.sql import (
    INSERT_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_SQL,
    INSERT_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_SQL,
    SHARDED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE_SQL,
    SHARDED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE_SQL,
    USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_READ_SQL,
    USAGE_REPORT_EVENTS_PREAGGREGATION_BOUNDS_SQL,
)
from posthog.temporal.usage_report import event_preaggregation, queries
from posthog.temporal.usage_report.activities import (
    USAGE_REPORT_EVENTS_PREAGGREGATION_WRITE_SETTINGS,
    usage_report_events_preaggregation_bucket_starts,
)
from posthog.temporal.usage_report.event_preaggregation import (
    get_all_event_metrics_in_period,
    get_teams_with_billable_event_count_in_period,
    get_teams_with_event_count_with_groups_in_period,
)


def test_preaggregated_tables_use_replacing_merge_tree() -> None:
    count_table_sql = SHARDED_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE_SQL()
    dedup_table_sql = SHARDED_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_TABLE_SQL()

    assert "ReplicatedReplacingMergeTree" in count_table_sql
    assert "ReplicatedReplacingMergeTree" in dedup_table_sql
    assert "computed_at" in count_table_sql
    assert "computed_at" in dedup_table_sql


def test_dedup_read_uses_latest_bucket_version() -> None:
    read_sql = USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_READ_SQL("raw_count")

    assert "latest_bucket_versions" in read_sql
    assert "d.computed_at = latest_bucket_versions.computed_at" in read_sql
    assert "max(d.raw_count) AS count" in read_sql
    assert "GROUP BY d.date, d.bucket_start, d.team_id, d.usage_kind, d.event" in read_sql
    assert "FINAL" not in read_sql

    with pytest.raises(ValueError):
        USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_READ_SQL("unique_count")


def test_insert_sql_uses_inserted_at_buckets_and_billing_grain() -> None:
    count_insert_sql = INSERT_USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_SQL()
    dedup_insert_sql = INSERT_USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_SQL()

    assert "FROM events_recent" in count_insert_sql
    assert "toStartOfInterval(inserted_at, INTERVAL 15 MINUTE)" in count_insert_sql
    assert "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '') != ''" in count_insert_sql
    assert "JSONExtractString(properties, '$group_0')" not in count_insert_sql
    assert "$group_0 != ''" not in count_insert_sql

    assert "FROM events_recent" in dedup_insert_sql
    assert "'all' AS usage_kind" in dedup_insert_sql
    assert "'enhanced_persons' AS usage_kind" in dedup_insert_sql
    assert "GROUP BY date, bucket_start, team_id, usage_kind, event" in dedup_insert_sql
    assert "uniqExact" not in dedup_insert_sql
    assert "unique_count" not in dedup_insert_sql
    assert "lib" not in dedup_insert_sql


def test_watermark_bounds_return_contiguous_requested_prefix() -> None:
    bounds_sql = USAGE_REPORT_EVENTS_PREAGGREGATION_BOUNDS_SQL()

    assert "bucket_start >= requested_begin" in bounds_sql
    assert "bucket_start < requested_end" in bounds_sql
    assert "row_number() OVER (ORDER BY bucket_start) - 1 AS bucket_index" in bounds_sql
    assert "expected_bucket_index" in bounds_sql
    assert "WHERE bucket_index = expected_bucket_index" in bounds_sql


def test_preaggregation_bucket_starts_overlap_recent_closed_buckets() -> None:
    now = datetime(2026, 6, 4, 12, 52, tzinfo=UTC)

    assert usage_report_events_preaggregation_bucket_starts(
        now,
        bucket_count=2,
        freshness_delay_minutes=5,
    ) == [
        datetime(2026, 6, 4, 12, 15, tzinfo=UTC),
        datetime(2026, 6, 4, 12, 30, tzinfo=UTC),
    ]


def test_preaggregation_writer_uses_synchronous_distributed_inserts() -> None:
    assert USAGE_REPORT_EVENTS_PREAGGREGATION_WRITE_SETTINGS["insert_distributed_sync"] == 1


def test_temporal_query_registry_uses_event_preaggregation_wrappers() -> None:
    specs = {spec.name: spec for spec in queries.QUERIES}

    assert (
        queries.get_teams_with_billable_event_count_in_period
        is event_preaggregation.get_teams_with_billable_event_count_in_period
    )
    assert (
        queries.get_teams_with_billable_enhanced_persons_event_count_in_period
        is event_preaggregation.get_teams_with_billable_enhanced_persons_event_count_in_period
    )
    assert (
        specs["teams_with_event_count_with_groups_in_period"].fn
        is event_preaggregation.get_teams_with_event_count_with_groups_in_period
    )
    assert specs["all_event_metrics"].fn is event_preaggregation.get_all_event_metrics_in_period


@override_settings(USE_USAGE_REPORT_EVENTS_PREAGGREGATION=True)
def test_billable_event_count_uses_preaggregation_and_events_recent_tail_for_raw_counts() -> None:
    now = datetime.now(UTC)
    end = datetime(now.year, now.month, now.day, tzinfo=UTC)
    begin = end - timedelta(days=1)
    max_bucket_end = now - timedelta(minutes=10)

    with patch("posthog.temporal.usage_report.event_preaggregation.sync_execute") as sync_execute_mock:
        sync_execute_mock.side_effect = [
            [(begin - timedelta(minutes=15), max_bucket_end)],
            [(1, 10)],
            [(1, 2), (2, 3)],
        ]

        result = get_teams_with_billable_event_count_in_period(begin, end, count_distinct=False)

    assert result == [(1, 12), (2, 3)]
    preaggregated_sql = sync_execute_mock.call_args_list[1].args[0]
    assert "usage_report_events_dedup_preaggregated" in preaggregated_sql
    assert "latest_bucket_versions" in preaggregated_sql
    assert "d.computed_at = latest_bucket_versions.computed_at" in preaggregated_sql
    assert "FROM events_recent" in sync_execute_mock.call_args_list[2].args[0]
    assert "inserted_at >= %(max_bucket_end)s" in sync_execute_mock.call_args_list[2].args[0]


@override_settings(USE_USAGE_REPORT_EVENTS_PREAGGREGATION=True)
def test_distinct_billable_event_count_does_not_sum_bucket_uniques() -> None:
    now = datetime.now(UTC)
    end = datetime(now.year, now.month, now.day, tzinfo=UTC)
    begin = end - timedelta(days=1)

    with (
        patch("posthog.temporal.usage_report.event_preaggregation.sync_execute") as sync_execute_mock,
        patch(
            "posthog.temporal.usage_report.event_preaggregation._legacy_get_billable_event_count",
            return_value=[(1, 1)],
        ) as legacy_billable_count_mock,
    ):
        result = get_teams_with_billable_event_count_in_period(begin, end, count_distinct=True)

    assert result == [(1, 1)]
    sync_execute_mock.assert_not_called()
    legacy_billable_count_mock.assert_called_once_with(begin, end, count_distinct=True)


@override_settings(USE_USAGE_REPORT_EVENTS_PREAGGREGATION=True)
def test_old_billable_backfill_does_not_use_events_recent_tail() -> None:
    now = datetime.now(UTC)
    end = datetime(now.year, now.month, now.day, tzinfo=UTC) - timedelta(days=8)
    begin = end - timedelta(days=1)

    with (
        patch("posthog.temporal.usage_report.event_preaggregation.sync_execute") as sync_execute_mock,
        patch(
            "posthog.temporal.usage_report.event_preaggregation._legacy_get_billable_event_count",
            return_value=[(1, 5)],
        ) as legacy_billable_count_mock,
    ):
        result = get_teams_with_billable_event_count_in_period(begin, end, count_distinct=False)

    assert result == [(1, 5)]
    sync_execute_mock.assert_not_called()
    legacy_billable_count_mock.assert_called_once_with(begin, end, count_distinct=False)


@override_settings(USE_USAGE_REPORT_EVENTS_PREAGGREGATION=True)
def test_group_count_tail_uses_events_recent_properties_for_group_detection() -> None:
    now = datetime.now(UTC)
    end = datetime(now.year, now.month, now.day, tzinfo=UTC)
    begin = end - timedelta(days=1)

    with patch("posthog.temporal.usage_report.event_preaggregation.sync_execute") as sync_execute_mock:
        sync_execute_mock.side_effect = [
            [(begin, end)],
            [(1, 10)],
            [(1, 2), (2, 3)],
        ]

        result = get_teams_with_event_count_with_groups_in_period(begin, end)

    assert result == [(1, 12), (2, 3)]
    tail_sql = sync_execute_mock.call_args_list[2].args[0]
    assert "FROM events_recent" in tail_sql
    assert "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '') != ''" in tail_sql
    assert "JSONExtractString(properties, '$group_0')" not in tail_sql
    assert "$group_0 != ''" not in tail_sql


@override_settings(USE_USAGE_REPORT_EVENTS_PREAGGREGATION=True)
def test_event_metrics_preaggregation_collapses_full_replacing_key() -> None:
    now = datetime.now(UTC)
    end = datetime(now.year, now.month, now.day, tzinfo=UTC)
    begin = end - timedelta(days=1)

    with patch("posthog.temporal.usage_report.event_preaggregation.sync_execute") as sync_execute_mock:
        sync_execute_mock.side_effect = [
            [(begin, end)],
            [(1, "web_events", 10)],
            [(1, "web_events", 2), (2, "node_events", 3)],
        ]

        result = get_all_event_metrics_in_period(begin, end)

    assert result["web_events"] == [(1, 12)]
    assert result["node_events"] == [(2, 3)]
    preaggregated_sql = sync_execute_mock.call_args_list[1].args[0]
    assert "latest_bucket_versions" in preaggregated_sql
    assert "c.computed_at = latest_bucket_versions.computed_at" in preaggregated_sql
    assert "max(c.event_count) AS count" in preaggregated_sql
    assert "person_mode" in preaggregated_sql
    assert "has_group" in preaggregated_sql
    assert "GROUP BY c.date, c.bucket_start, c.team_id, c.person_mode, c.lib, c.event, c.has_group" in preaggregated_sql
