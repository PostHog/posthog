from posthog.performance.sql import (
    DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL,
    KAFKA_PERFORMANCE_EVENTS_TABLE_SQL,
    PERFORMANCE_EVENTS_TABLE_MV_SQL,
    PERFORMANCE_EVENTS_TABLE_SQL,
    WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL,
)


def test_snapshot_performance_events_table(snapshot, settings):
    assert PERFORMANCE_EVENTS_TABLE_SQL() == snapshot


def test_snapshot_kafka_performance_events_table(snapshot, settings):
    assert KAFKA_PERFORMANCE_EVENTS_TABLE_SQL() == snapshot


def test_snapshot_performance_events__mv_table(snapshot, settings):
    assert PERFORMANCE_EVENTS_TABLE_MV_SQL() == snapshot


def test_snapshot_distributed_performance_events_table(snapshot, settings):
    assert DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL() == snapshot


def test_writable_distributed_performance_events_table(snapshot, settings):
    assert WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL() == snapshot
