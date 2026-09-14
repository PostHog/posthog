import pytest
from unittest.mock import patch

import grpc

from posthog.usage_ingestion.client import UsageRecord, _timeout_seconds, areport_usage, report_usage, team_is_enabled

ERRORS = [grpc.RpcError(), RuntimeError("boom")]
REPORTING_ENV = {"USAGE_INGESTION_ADDR": "localhost:1", "USAGE_INGESTION_REPORT_TEAMS": "*"}
RECORD = UsageRecord(record_id="r", producer_id="p", team_id=2, usage_key="k", unit="rows", quantity=1)


def test_team_is_enabled_uses_the_shared_team_list(monkeypatch) -> None:
    monkeypatch.setenv("USAGE_INGESTION_REPORT_TEAMS", "2, 4")

    assert team_is_enabled(2)
    assert team_is_enabled(4)
    assert not team_is_enabled(3)


def test_team_is_enabled_supports_all_teams(monkeypatch) -> None:
    monkeypatch.setenv("USAGE_INGESTION_REPORT_TEAMS", "*")

    assert team_is_enabled(123)


def test_timeout_converts_milliseconds_to_the_seconds_grpc_expects(monkeypatch) -> None:
    monkeypatch.delenv("USAGE_INGESTION_TIMEOUT_MS", raising=False)
    assert _timeout_seconds() == 5.0

    monkeypatch.setenv("USAGE_INGESTION_TIMEOUT_MS", "250")
    assert _timeout_seconds() == 0.25


# Every producer calls these after committing work of its own, so a raise here fails an activity
# that is already done, and the retry re-runs everything that ran before it.
@pytest.mark.parametrize("error", ERRORS)
def test_reporting_never_raises_into_the_producer(error: Exception) -> None:
    with patch.dict("os.environ", REPORTING_ENV):
        with patch("posthog.usage_ingestion.client.grpc.insecure_channel", side_effect=error):
            report_usage([RECORD], site="test")


@pytest.mark.parametrize("error", ERRORS)
async def test_async_reporting_never_raises_into_the_producer(error: Exception) -> None:
    with patch.dict("os.environ", REPORTING_ENV):
        with patch("posthog.usage_ingestion.client.grpc.aio.insecure_channel", side_effect=error):
            await areport_usage([RECORD], site="test")
