from unittest import mock

import dagster
from dagster import DagsterRunStatus
from slack_sdk.errors import SlackApiError

from posthog.dags.common import JobOwners
from posthog.dags.slack_alerts import (
    SLACK_SECTION_TEXT_LIMIT,
    _truncate_for_slack,
    get_job_owner_for_alert,
    send_slack_alert,
    should_suppress_alert,
)


class TestSlackAlertsRouting:
    def test_regular_job_uses_owner_tag(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "some_regular_job"
        mock_run.tags = {"owner": JobOwners.TEAM_CLICKHOUSE.value}

        error_message = "Some regular error message"

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == JobOwners.TEAM_CLICKHOUSE.value

    def test_asset_job_with_web_steps_routes_to_web_analytics(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "__ASSET_JOB"
        mock_run.tags = {"owner": JobOwners.TEAM_CLICKHOUSE.value}  # Original owner is different

        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['web_pre_aggregated_bounces', 'web_pre_aggregated_stats']."

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == JobOwners.TEAM_WEB_ANALYTICS.value

    def test_asset_job_with_mixed_steps_routes_to_web_analytics(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "__ASSET_JOB"
        mock_run.tags = {"owner": JobOwners.TEAM_DATA_MODELING.value}

        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['some_other_asset', 'web_pre_aggregated_bounces', 'clickhouse_asset']."

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == JobOwners.TEAM_WEB_ANALYTICS.value

    def test_asset_job_without_web_steps_uses_original_owner(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "__ASSET_JOB"
        mock_run.tags = {"owner": JobOwners.TEAM_DATA_MODELING.value}

        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['exchange_rates_daily', 'exchange_rates_hourly']."

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == JobOwners.TEAM_DATA_MODELING.value

    def test_asset_job_no_failed_steps_uses_original_owner(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "__ASSET_JOB"
        mock_run.tags = {"owner": JobOwners.TEAM_CLICKHOUSE.value}

        error_message = "Some generic asset job error message"

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == JobOwners.TEAM_CLICKHOUSE.value

    def test_asset_job_no_owner_tag_defaults_to_unknown(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "__ASSET_JOB"
        mock_run.tags = {}

        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['some_asset']."

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == "unknown"


class TestConsecutiveFailureSuppression:
    def test_suppression_with_fewer_runs_than_threshold(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        mock_records = [
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
        ]
        mock_instance.get_run_records.return_value = mock_records

        result = should_suppress_alert(mock_context, "some_job", threshold=3)

        assert result is True
        mock_context.log.info.assert_called()

    def test_no_suppression_when_threshold_reached(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        mock_records = [
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
        ]
        mock_instance.get_run_records.return_value = mock_records

        result = should_suppress_alert(mock_context, "some_job", threshold=3)

        assert result is False
        mock_context.log.warning.assert_called()

    def test_suppression_with_mixed_success_and_failure(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        mock_records = [
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.SUCCESS)),
        ]
        mock_instance.get_run_records.return_value = mock_records

        result = should_suppress_alert(mock_context, "some_job", threshold=3)

        assert result is True
        mock_context.log.info.assert_called()

    def test_suppression_with_one_success_among_failures(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        mock_records = [
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.SUCCESS)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
        ]
        mock_instance.get_run_records.return_value = mock_records

        result = should_suppress_alert(mock_context, "some_job", threshold=3)

        assert result is True
        mock_context.log.info.assert_called()

    def test_error_handling_does_not_suppress(self):
        """Should NOT suppress alert if there's an error checking run history so we keep the existing behavior"""
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        # Mock an exception when getting run records
        mock_instance.get_run_records.side_effect = Exception("Database connection error")

        result = should_suppress_alert(mock_context, "some_job", threshold=3)

        assert result is False
        mock_context.log.exception.assert_called()

    def test_threshold_of_one_never_suppresses(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        # Mock 1 run record (failure)
        mock_records = [
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
        ]
        mock_instance.get_run_records.return_value = mock_records

        result = should_suppress_alert(mock_context, "some_job", threshold=1)

        assert result is False
        mock_context.log.warning.assert_called()


class TestTruncateForSlack:
    def test_short_text_is_unchanged(self):
        assert _truncate_for_slack("a short error", 3000) == "a short error"

    def test_text_at_limit_is_unchanged(self):
        text = "x" * 100
        assert _truncate_for_slack(text, 100) == text

    def test_long_text_is_truncated_within_limit(self):
        # A verbose failure like a k8s ApiException must not exceed Slack's section limit.
        text = "x" * 10_000
        result = _truncate_for_slack(text, SLACK_SECTION_TEXT_LIMIT)

        assert len(result) <= SLACK_SECTION_TEXT_LIMIT
        assert "…(truncated)…" in result

    def test_truncation_keeps_head_and_tail(self):
        # Head carries the exception type, tail carries the root cause — keep both.
        text = "HEAD_MARKER" + ("m" * 5000) + "TAIL_MARKER"
        result = _truncate_for_slack(text, 200)

        assert result.startswith("HEAD_MARKER")
        assert result.endswith("TAIL_MARKER")
        assert len(result) <= 200


class TestSendSlackAlert:
    def _blocks(self):
        return [{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}]

    def test_success_sends_blocks_with_text_fallback(self):
        context = mock.MagicMock()
        client = mock.MagicMock()

        send_slack_alert(context, client, "#alerts-clickhouse", self._blocks(), "fallback")

        client.chat_postMessage.assert_called_once_with(
            channel="#alerts-clickhouse", blocks=self._blocks(), text="fallback"
        )
        context.log.info.assert_called()

    def _block_rejection(self, code="invalid_blocks"):
        return SlackApiError(message=code, response={"ok": False, "error": code})

    def test_blocks_rejected_falls_back_to_text_only(self):
        context = mock.MagicMock()
        client = mock.MagicMock()
        # Slack rejected the block payload outright, so the message did not post; retry text-only.
        client.chat_postMessage.side_effect = [self._block_rejection(), {"ok": True}]

        send_slack_alert(context, client, "#test-channel", self._blocks(), "fallback")

        assert client.chat_postMessage.call_count == 2
        # The retry must be text-only (no blocks) so a formatting/size issue can't suppress it.
        retry_kwargs = client.chat_postMessage.call_args_list[1].kwargs
        assert retry_kwargs == {"channel": "#test-channel", "text": "fallback"}

    def test_ambiguous_api_error_does_not_retry(self):
        context = mock.MagicMock()
        client = mock.MagicMock()
        # A non-rejection API error (e.g. rate limited) may mean the blocks posted — don't duplicate.
        client.chat_postMessage.side_effect = self._block_rejection("ratelimited")

        send_slack_alert(context, client, "#test-channel", self._blocks(), "fallback")

        assert client.chat_postMessage.call_count == 1
        context.log.exception.assert_called()

    def test_non_api_exception_does_not_retry(self):
        context = mock.MagicMock()
        client = mock.MagicMock()
        # A raise while reading/parsing the response is ambiguous — the message may have posted.
        client.chat_postMessage.side_effect = ConnectionError("read timeout")

        send_slack_alert(context, client, "#test-channel", self._blocks(), "fallback")

        assert client.chat_postMessage.call_count == 1
        context.log.exception.assert_called()

    def test_text_only_fallback_failing_does_not_raise(self):
        context = mock.MagicMock()
        client = mock.MagicMock()
        # Blocks rejected, then the text-only retry also fails — must not crash the sensor tick.
        client.chat_postMessage.side_effect = [self._block_rejection(), Exception("slack down")]

        send_slack_alert(context, client, "#test-channel", self._blocks(), "fallback")

        assert client.chat_postMessage.call_count == 2
        context.log.exception.assert_called()
