from unittest.mock import patch

import grpc
from parameterized import parameterized

from posthog.usage_ingestion.client import UsageRecord, _timeout_seconds, report_usage, team_is_enabled


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


# Every producer calls this after committing work of its own, so a raise here fails an activity
# that is already done, and the retry re-runs everything that ran before it.
@parameterized.expand([("rpc_error", grpc.RpcError()), ("anything_else", RuntimeError("boom"))])
def test_reporting_never_raises_into_the_producer(_name: str, error: Exception) -> None:
    record = UsageRecord(record_id="r", producer_id="p", team_id=2, usage_key="k", unit="rows", quantity=1)

    with patch.dict("os.environ", {"USAGE_INGESTION_ADDR": "localhost:1", "USAGE_INGESTION_REPORT_TEAMS": "*"}):
        with patch("posthog.usage_ingestion.client.grpc.insecure_channel", side_effect=error):
            report_usage([record], site="test")
