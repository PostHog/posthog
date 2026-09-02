import pytest

from posthog.temporal.ai_observability.evaluation_payload import (
    PAYLOAD_BYTES_EXPR,
    payload_budget_bytes,
    should_skip_for_payload,
)


class TestPayloadBudget:
    def test_budget_tracks_the_targets_judge_budget(self):
        assert payload_budget_bytes(500_000) > payload_budget_bytes(150_000)

    def test_expression_covers_every_column_the_fetch_materializes(self):
        """A column the fetch pulls but the sum omits is payload the cap cannot see, which is how
        the event-count cap failed in the first place."""
        for column in ("properties", "input", "output", "output_choices", "input_state", "output_state", "tools"):
            assert column in PAYLOAD_BYTES_EXPR

    @pytest.mark.parametrize(
        "target,payload_bytes,budget_bytes,expected_skip",
        [
            # A session over budget is skipped: this is the case the event count cannot catch,
            # since few-but-enormous events sit far under any row cap.
            ("session", 5_000_000, 4_000_000, True),
            ("session", 1_000, 4_000_000, False),
            # Trace is measured but never skipped. Trace evaluations already run in production, so
            # enforcing a new dimension on them would silently drop units that grade fine today.
            ("trace", 5_000_000, 1_200_000, False),
            ("trace", 1_000, 1_200_000, False),
        ],
    )
    def test_session_enforces_and_trace_only_records(self, target, payload_bytes, budget_bytes, expected_skip):
        assert (
            should_skip_for_payload(target=target, payload_bytes=payload_bytes, budget_bytes=budget_bytes)
            is expected_skip
        )
