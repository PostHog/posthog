import threading

from posthog.hogql.query_stats import get_active, query_stats_scope, record, use


def test_nested_scopes_sum_into_one_accumulator():
    with query_stats_scope() as outer:
        record(rows_read=1, bytes_read=10, duration_ms=5.0)
        with query_stats_scope() as inner:
            assert inner is outer
            record(rows_read=2, bytes_read=20, duration_ms=7.0)
        record(rows_read=4, bytes_read=40, duration_ms=1.0)

    assert (outer.rows_read, outer.bytes_read, outer.duration_ms) == (7, 70, 13.0)


def test_record_outside_a_scope_is_ignored():
    record(rows_read=5, bytes_read=50, duration_ms=9.0)

    with query_stats_scope() as stats:
        pass

    assert (stats.rows_read, stats.bytes_read, stats.duration_ms) == (0, 0, 0.0)


def test_use_installs_the_accumulator_in_another_thread():
    with query_stats_scope() as stats:
        handed_over = get_active()

        def worker() -> None:
            with use(handed_over):
                record(rows_read=3, bytes_read=30, duration_ms=2.0)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

    assert (stats.rows_read, stats.bytes_read, stats.duration_ms) == (3, 30, 2.0)
