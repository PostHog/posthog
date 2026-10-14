from datetime import UTC, datetime, timedelta
from uuid import uuid4

from django.test import SimpleTestCase

from posthog.clickhouse.client import sync_execute
from posthog.management.commands.inspect_event_usage_dates import inspect_event_usage_dates


class TestInspectEventUsageDates(SimpleTestCase):
    def test_groups_source_dates_without_moving_usage_out_of_the_capture_day(self) -> None:
        day = datetime(2026, 7, 1, tzinfo=UTC)
        team_id = uuid4().int % 1_000_000_000 + 1_000_000_000
        base = {
            "schema_version": 1,
            "producer_id": "test-producer",
            "team_id": team_id,
            "organization_id": uuid4(),
            "usage_key": "events",
            "unit": "events",
            "quantity": 1,
            "timestamp": day,
            "inserted_at": day,
        }
        rows = [{**base, "record_id": f"{date}:{'a' * 32}"} for date in ("2026-05-15", "2026-07-01", "2026-08-01")]
        rows.extend(
            [
                rows[0],
                {**base, "record_id": "unrecognized"},
                {**base, "record_id": f"2026-07-01:{'b' * 32}", "timestamp": day + timedelta(days=1)},
                {**base, "record_id": f"2026-07-01:{'c' * 32}", "team_id": team_id + 1},
                {**base, "record_id": f"2026-05-15:{'a' * 32}", "usage_key": "enhanced_person_events"},
            ]
        )
        sync_execute(
            """INSERT INTO sharded_billing_usage_records
            (schema_version, record_id, producer_id, team_id, organization_id, usage_key, unit, quantity, timestamp, inserted_at)
            VALUES""",
            rows,
        )
        result = inspect_event_usage_dates(team_id=team_id, capture_day=day)
        assert result == [
            {"usage_key": "enhanced_person_events", "unit": "events", "source_period": "earlier", "quantity": 1},
            *[
                {"usage_key": "events", "unit": "events", "source_period": period, "quantity": 1}
                for period in ("earlier", "later", "same_day", "unknown")
            ],
        ]
