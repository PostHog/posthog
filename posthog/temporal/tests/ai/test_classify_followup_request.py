from datetime import UTC, datetime

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.ai.slack_app.activities.followups import classify_followup_request

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)


class TestClassifyFollowupRequest:
    @parameterized.expand(
        [
            (
                "schedule_with_valid_run_at",
                '{"intent": "schedule", "run_at": "2026-08-14T09:00:00-07:00", "what": "Check cohort activation"}',
                "schedule",
                "2026-08-14T09:00:00-07:00",
            ),
            ("cancel", '{"intent": "cancel"}', "cancel", None),
            ("none", '{"intent": "none"}', "none", None),
            ("missing_intent", "{}", "none", None),
            ("unknown_intent", '{"intent": "later"}', "none", None),
            # A past run_at would arm a Temporal schedule that never fires while the user
            # believes the check is scheduled; demote to none so the mention runs now instead.
            ("schedule_in_the_past", '{"intent": "schedule", "run_at": "2026-07-01T09:00:00+00:00"}', "none", None),
            ("schedule_beyond_horizon", '{"intent": "schedule", "run_at": "2028-01-01T09:00:00+00:00"}', "none", None),
            ("schedule_malformed_run_at", '{"intent": "schedule", "run_at": "in two weeks"}', "none", None),
            ("schedule_missing_run_at", '{"intent": "schedule"}', "none", None),
            # A zulu-suffixed or offset-less datetime still parses (treated as UTC).
            ("schedule_zulu_run_at", '{"intent": "schedule", "run_at": "2026-08-14T09:00:00Z"}', "schedule", None),
            ("not_json", "sure, scheduling that!", "none", None),
        ]
    )
    def test_llm_response_shapes(self, _name, content, expected_intent, expected_run_at):
        result, _prompt = self._run_with_llm_content(content)

        assert result.intent == expected_intent
        if expected_run_at is not None:
            assert result.run_at == datetime.fromisoformat(expected_run_at).isoformat()
        if expected_intent != "schedule":
            assert result.run_at is None

    def test_llm_failure_defaults_to_none(self):
        with patch(
            "posthog.temporal.ai.slack_app.activities.followups.get_llm_client",
            side_effect=RuntimeError("boom"),
        ):
            result = classify_followup_request("@PostHog check this in two weeks", now=NOW, project_timezone="UTC")
        assert result.intent == "none"

    def test_executable_task_comes_from_latest_mention(self):
        result, prompt = self._run_with_llm_content(
            '{"intent": "schedule", "run_at": "2026-08-14T09:00:00+00:00", "what": "Ignore the requester"}'
        )

        assert result.what == "@PostHog check this in two weeks and report back here"
        assert "we should watch this after launch" not in prompt

    def _run_with_llm_content(self, content: str):
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content=content))]
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_response
        with patch(
            "posthog.temporal.ai.slack_app.activities.followups.get_llm_client",
            return_value=fake_client,
        ):
            result = classify_followup_request(
                "@PostHog check this in two weeks and report back here",
                now=NOW,
                project_timezone="US/Pacific",
            )
        prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        return result, prompt
