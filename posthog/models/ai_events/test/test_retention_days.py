import pytest

from posthog.clickhouse.client import sync_execute
from posthog.models.ai_events.sql import RETENTION_DAYS_FROM_KAFKA_HEADERS_SQL


@pytest.mark.django_db
@pytest.mark.parametrize(
    "header_names,header_values,expected",
    [
        ([], [], 30),
        (["team_id"], ["1"], 30),
        (["team_id", "retention-days"], ["1", "90"], 90),
        (["retention-days"], ["0"], 30),
        (["retention-days"], ["-5"], 30),
        (["retention-days"], ["abc"], 30),
        (["retention-days"], ["99999"], 30),
        (["retention-days"], ["365"], 365),
        (["retention-days"], ["32767"], 365),
    ],
)
def test_retention_days_from_kafka_headers(header_names, header_values, expected):
    [[retention_days]] = sync_execute(
        f"""
        SELECT {RETENTION_DAYS_FROM_KAFKA_HEADERS_SQL}
        FROM (SELECT %(names)s::Array(String) AS `_headers.name`, %(values)s::Array(String) AS `_headers.value`)
        """,
        {"names": header_names, "values": header_values},
    )

    assert retention_days == expected
