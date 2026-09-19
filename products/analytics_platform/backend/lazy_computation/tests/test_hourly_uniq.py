from datetime import UTC, datetime

from django.test import SimpleTestCase

from posthog.hogql import ast

from products.analytics_platform.backend.lazy_computation.hourly_uniq import _only, plan_hourly_uniq

# Invented independently: a single metric, with deliberately different projection/filter shapes.
SQL = """SELECT toStartOfHour(timestamp) AS bucket, uniqIf(person_id, event = 'sample') AS visitors
FROM events WHERE timestamp >= toStartOfHour(now()) - INTERVAL 240 HOUR
AND timestamp < toStartOfHour(now()) AND properties.category = 'demo'
GROUP BY bucket ORDER BY bucket"""
ANCHOR = datetime(2026, 2, 12, 12, tzinfo=UTC)


class TestHourlyUniqPlan(SimpleTestCase):
    def test_zero_is_not_an_absent_ast_field(self):
        assert not _only(ast.Constant(value=0), set())
        assert _only(ast.Constant(value=None), set())

    def test_plan_preserves_input_and_parameterizes_build_range(self):
        plan = plan_hourly_uniq(SQL, now=ANCHOR, timezone="UTC")
        assert plan is not None
        assert plan.start == datetime(2026, 2, 2, 12, tzinfo=UTC)
        assert plan.end == ANCHOR
        assert len(plan.metrics) == 1
        sql = repr(plan.insert_query)
        assert "uniqStateIf" in sql
        assert "name='now'" not in sql
        assert "240" not in sql
        assert "time_window_min" in sql
        assert "time_window_max" in sql

    def test_simple_outer_projection_is_supported(self):
        wrapped = f"SELECT bucket, greatest(visitors, 2) AS adjusted FROM ({SQL}) ORDER BY bucket"
        assert plan_hourly_uniq(wrapped, now=ANCHOR, timezone="UTC") is not None

    def test_rejects_semantics_it_cannot_preserve(self):
        queries = [
            SQL.replace("uniqIf(person_id,", "sumIf(person_id,"),
            SQL.replace("properties.category = 'demo'", "rand() > 1"),
            SQL + " LIMIT 10",
            SQL.replace("GROUP BY bucket", "GROUP BY bucket HAVING visitors > 1"),
            SQL.replace("FROM events", "FROM events e"),
            SQL.replace("FROM events", "FROM events JOIN persons ON events.person_id = persons.id"),
            SQL.replace("properties.category = 'demo'", "person.properties.name IS NOT NULL"),
            SQL.replace("properties.category = 'demo'", "{filters}"),
            SQL.replace("properties.category = 'demo'", "timestamp > now() - INTERVAL 1 DAY"),
        ]
        for query in queries:
            with self.subTest(query=query):
                assert plan_hourly_uniq(query, now=ANCHOR, timezone="UTC") is None

    def test_rejects_non_hour_aligned_timezones_and_dst(self):
        assert plan_hourly_uniq(SQL, now=ANCHOR, timezone="Asia/Kathmandu") is None
        assert plan_hourly_uniq(SQL, now=datetime(2026, 10, 27, tzinfo=UTC), timezone="Europe/Amsterdam") is None

    def test_reserved_aliases_fail_closed(self):
        assert plan_hourly_uniq(SQL.replace("AS visitors", "AS uniq_state"), now=ANCHOR, timezone="UTC") is None

    def test_query_changes_do_not_share_materialization_identity(self):
        plan = plan_hourly_uniq(SQL, now=ANCHOR, timezone="UTC")
        moved = plan_hourly_uniq(SQL, now=ANCHOR.replace(hour=13), timezone="UTC")
        other = plan_hourly_uniq(SQL.replace("'demo'", "'different'"), now=ANCHOR, timezone="UTC")
        assert plan and moved and other
        assert repr(plan.insert_query) == repr(moved.insert_query)
        assert repr(plan.insert_query) != repr(other.insert_query)

    def test_duplicate_metric_is_stored_once(self):
        sql = SQL.replace(
            "uniqIf(person_id, event = 'sample') AS visitors",
            "uniqIf(person_id, event = 'sample') + uniqIf(person_id, event = 'sample') AS visitors",
        )
        plan = plan_hourly_uniq(sql, now=ANCHOR, timezone="UTC")
        assert plan and len(plan.metrics) == 1

    def test_requires_a_deterministic_time_order(self):
        assert plan_hourly_uniq(SQL.replace(" ORDER BY bucket", ""), now=ANCHOR, timezone="UTC") is None
        assert plan_hourly_uniq(SQL.replace("ORDER BY bucket", "ORDER BY visitors"), now=ANCHOR, timezone="UTC") is None
        assert plan_hourly_uniq(SQL + " DESC", now=ANCHOR, timezone="UTC") is not None


class TestHourlyUniqFreshness(SimpleTestCase):
    def test_age_based_refresh_schedule(self):
        from datetime import timedelta

        from products.analytics_platform.backend.lazy_computation.hourly_uniq_cache import HourlyUniqFreshness

        policy = HourlyUniqFreshness.age_based(revision="example")
        schedule = policy.schedule(ANCHOR)
        assert policy.live_hours == 0
        assert schedule.get_ttl(ANCHOR - timedelta(days=1)) == 3600
        assert schedule.get_ttl(ANCHOR - timedelta(days=3)) == 18 * 3600
        assert schedule.get_ttl(ANCHOR - timedelta(days=6)) == 7 * 86400
        assert schedule.max_window_days == 1
        assert schedule.default_ttl_jitter_seconds == 6 * 3600

    def test_rejects_invalid_age_bands(self):
        from products.analytics_platform.backend.lazy_computation.hourly_uniq_cache import HourlyUniqFreshness

        for bands in [((96, 3600), (48, 7200)), ((0, 3600),), ((48, 0),), ((48, 999999),)]:
            with self.assertRaises(ValueError):
                HourlyUniqFreshness(86400, 0, "example", refresh_bands=bands)
