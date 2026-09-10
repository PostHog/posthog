import threading

from posthog.hogql.query_stats import get_active, query_stats_scope, record, use


def test_scope_sums_nested_records_and_ignores_what_was_recorded_outside_it():
    record(rows_read=5, duration_ms=9.0)

    with query_stats_scope() as outer:
        record(rows_read=1, duration_ms=5.0)
        with query_stats_scope() as inner:
            assert inner is outer
            record(rows_read=2, duration_ms=7.0)
        record(rows_read=4, duration_ms=1.0)

    assert (outer.rows_read, outer.duration_ms) == (7, 13.0)


def test_use_installs_the_accumulator_in_another_thread():
    with query_stats_scope() as stats:
        handed_over = get_active()

        def worker() -> None:
            with use(handed_over):
                record(rows_read=3, duration_ms=2.0)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

    assert (stats.rows_read, stats.duration_ms) == (3, 2.0)
