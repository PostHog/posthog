"""
Real-ClickHouse integration tests for point-in-time person properties.

This file used to mock ``sync_execute``, which made the file's name a lie and
let SQL typos / column-order mistakes / UNION-ALL ordering bugs sail through
green. Each test now seeds events into ClickHouse and exercises the real query.
"""

from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.models.person.point_in_time_properties import build_person_properties_at_time


class TestPointInTimePropertiesClickhouse(ClickhouseTestMixin, BaseTest):
    """Hits the real ClickHouse query — guards against SQL typos and the
    column-order / ORDER-BY-through-UNION-ALL pitfalls."""

    def test_chronological_set_resolution(self):
        distinct_id = "user-clickhouse-chrono"
        upper_bound = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)

        # Two $set events on the same key, written non-chronologically (later
        # event inserted first) — the production query must sort to give the
        # later value precedence.
        _create_event(
            event="$set",
            team=self.team,
            distinct_id=distinct_id,
            properties={"$set": {"name": "Final"}},
            timestamp=upper_bound - timedelta(hours=1),
        )
        _create_event(
            event="$set",
            team=self.team,
            distinct_id=distinct_id,
            properties={"$set": {"name": "Initial", "email": "user@example.com"}},
            timestamp=upper_bound - timedelta(hours=5),
        )
        flush_persons_and_events()

        properties = build_person_properties_at_time(
            self.team.pk,
            upper_bound,
            [distinct_id],
        )

        self.assertEqual(properties, {"name": "Final", "email": "user@example.com"})

    def test_set_once_first_write_wins(self):
        distinct_id = "user-clickhouse-set-once"
        upper_bound = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)

        _create_event(
            event="$set_once",
            team=self.team,
            distinct_id=distinct_id,
            properties={"$set_once": {"first_seen": "2024-05-01"}},
            timestamp=upper_bound - timedelta(hours=2),
        )
        _create_event(
            event="$set_once",
            team=self.team,
            distinct_id=distinct_id,
            properties={"$set_once": {"first_seen": "2024-05-15"}},
            timestamp=upper_bound - timedelta(hours=1),
        )
        flush_persons_and_events()

        properties = build_person_properties_at_time(
            self.team.pk,
            upper_bound,
            [distinct_id],
            include_set_once=True,
        )

        self.assertEqual(properties, {"first_seen": "2024-05-01"})

    def test_set_then_set_once_interleaving(self):
        """Mixed $set and $set_once events: $set always wins on its key, while
        $set_once only sticks for keys never set by anything else."""
        distinct_id = "user-clickhouse-interleave"
        upper_bound = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)

        _create_event(
            event="$set_once",
            team=self.team,
            distinct_id=distinct_id,
            properties={
                "$set_once": {
                    "first_seen": "2024-05-01",
                    "signup_source": "organic",
                }
            },
            timestamp=upper_bound - timedelta(hours=4),
        )
        _create_event(
            event="$set",
            team=self.team,
            distinct_id=distinct_id,
            properties={"$set": {"name": "Bob"}},
            timestamp=upper_bound - timedelta(hours=3),
        )
        # Later $set overrides signup_source set by the earlier $set_once.
        _create_event(
            event="$set",
            team=self.team,
            distinct_id=distinct_id,
            properties={"$set": {"signup_source": "facebook"}},
            timestamp=upper_bound - timedelta(hours=2),
        )
        # Later $set_once attempts to overwrite signup_source — must NOT win.
        _create_event(
            event="$set_once",
            team=self.team,
            distinct_id=distinct_id,
            properties={
                "$set_once": {
                    "signup_source": "twitter",
                    "utm_campaign": "winter",
                }
            },
            timestamp=upper_bound - timedelta(hours=1),
        )
        flush_persons_and_events()

        properties = build_person_properties_at_time(
            self.team.pk,
            upper_bound,
            [distinct_id],
            include_set_once=True,
        )

        self.assertEqual(
            properties,
            {
                "first_seen": "2024-05-01",
                "signup_source": "facebook",
                "name": "Bob",
                "utm_campaign": "winter",
            },
        )

    def test_only_non_property_events_returns_not_existed(self):
        # ``existed`` semantics: had any property-update event at or before timestamp.
        # A $pageview that doesn't carry a $set blob is not a property event by this
        # definition, so ``existed`` is False even though the person had activity.
        # Upstream existence (Postgres row) is established by the caller, not here.
        distinct_id = "user-clickhouse-pageview-only"
        upper_bound = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=distinct_id,
            properties={"url": "https://example.com"},
            timestamp=upper_bound - timedelta(hours=1),
        )
        flush_persons_and_events()

        properties = build_person_properties_at_time(
            self.team.pk,
            upper_bound,
            [distinct_id],
        )

        self.assertEqual(properties, {})

    def test_no_events_returns_empty_properties(self):
        upper_bound = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)

        properties = build_person_properties_at_time(
            self.team.pk,
            upper_bound,
            ["user-clickhouse-nonexistent"],
        )

        self.assertEqual(properties, {})

    def test_row_limit_truncates_oldest_first(self):
        """When the property row count exceeds row_limit, the inner ORDER BY ASC + LIMIT
        keeps the earliest rows. We assert that a property only present in the tail
        beyond the limit does NOT make it into the result."""
        distinct_id = "user-clickhouse-rowlimit"
        upper_bound = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        row_limit = 5

        # Insert row_limit + 1 chronologically-ordered events. The newest one
        # sets a unique key that should be dropped because the LIMIT cuts it off.
        for i in range(row_limit):
            _create_event(
                event="$set",
                team=self.team,
                distinct_id=distinct_id,
                properties={"$set": {f"key_{i}": f"value_{i}"}},
                timestamp=upper_bound - timedelta(hours=row_limit - i + 1),
            )
        _create_event(
            event="$set",
            team=self.team,
            distinct_id=distinct_id,
            properties={"$set": {"truncated_key": "should_be_missing"}},
            timestamp=upper_bound - timedelta(minutes=1),
        )
        flush_persons_and_events()

        properties = build_person_properties_at_time(
            self.team.pk,
            upper_bound,
            [distinct_id],
            row_limit=row_limit,
        )

        for i in range(row_limit):
            self.assertEqual(properties.get(f"key_{i}"), f"value_{i}")
        self.assertNotIn("truncated_key", properties)

    def test_happy_path_with_default_row_limit(self):
        # Happy path with no explicit row_limit — confirms the default flows through.
        distinct_id = "user-clickhouse-default-limit"
        upper_bound = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)

        _create_event(
            event="$set",
            team=self.team,
            distinct_id=distinct_id,
            properties={"$set": {"hello": "world"}},
            timestamp=upper_bound - timedelta(hours=1),
        )
        flush_persons_and_events()

        properties = build_person_properties_at_time(
            self.team.pk,
            upper_bound,
            [distinct_id],
        )

        self.assertEqual(properties, {"hello": "world"})
