import json
from pathlib import Path

import pytest

from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.hogai.session_summaries.session.stringify import SingleSessionSummaryStringifier
from ee.hogai.session_summaries.session_group.patterns import EnrichedSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.session_group.stringify import SessionGroupSummaryStringifier


class TestSingleSessionSummaryStringifier:
    def test_stringify_single_session_summary(self):
        input_path = Path(__file__).parent / "assets" / "single_session.json"
        output_path = Path(__file__).parent / "assets" / "single_session_stringified.md"
        with open(input_path) as f:
            input_data = json.load(f)
        with open(output_path) as f:
            output_data = f.read()
        # Ensure the input data is valid
        SessionSummarySerializer(data=input_data).is_valid(raise_exception=True)
        # Stringify and check the results
        stringifier = SingleSessionSummaryStringifier(input_data)
        stringified_data = stringifier.stringify_session()
        assert stringified_data.strip() == output_data.strip()

    @pytest.mark.parametrize(
        "abandonment,confusion,exception,expected_issues",
        [
            (False, False, None, ""),
            (True, False, None, "Issues noticed: abandonment. "),
            (False, True, None, "Issues noticed: confusion. "),
            (False, False, "blocking", "Issues noticed: blocking exception. "),
            (True, True, None, "Issues noticed: abandonment, confusion. "),
            (True, True, "non-blocking", "Issues noticed: abandonment, confusion, non-blocking exception. "),
        ],
    )
    def test_event_stringification_with_various_issues(self, abandonment, confusion, exception, expected_issues):
        event = {
            "description": "User clicked button",
            "abandonment": abandonment,
            "confusion": confusion,
            "exception": exception,
            "milliseconds_since_start": 5000,
            "event": "$autocapture",
            "event_type": "click",
            "event_uuid": "test-uuid-123",
        }
        stringifier = SingleSessionSummaryStringifier({})
        result = stringifier.stringify_event(event)
        expected = (
            f'\n- {expected_issues}User clicked button at 00:00:05, as "$autocapture" (click) event '
            f"(event_uuid: `test-uuid-123`)."
        )
        assert result == expected

    def test_event_without_event_type(self):
        event = {
            "description": "Custom event triggered",
            "abandonment": False,
            "confusion": False,
            "exception": None,
            "milliseconds_since_start": 1000,
            "event": "$pageview",
            "event_type": None,
            "event_uuid": "test-uuid",
        }
        stringifier = SingleSessionSummaryStringifier({})
        result = stringifier.stringify_event(event)
        expected = '\n- Custom event triggered at 00:00:01, as "$pageview" event (event_uuid: `test-uuid`).'
        assert result == expected


class TestSessionGroupSummaryStringifier:
    def test_stringify_group_session_summary(self):
        input_path = Path(__file__).parent / "assets" / "group_session.json"
        output_path = Path(__file__).parent / "assets" / "group_session_stringified.md"
        with open(input_path) as f:
            input_data = json.load(f)
        with open(output_path) as f:
            output_data = f.read()
        # Ensure the input data is valid
        EnrichedSessionGroupSummaryPatternsList.model_validate(input_data)
        # Stringify and check the results
        stringifier = SessionGroupSummaryStringifier(input_data)
        stringified_data = stringifier.stringify_patterns()
        assert stringified_data.strip() == output_data.strip()
