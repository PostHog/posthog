import json
from pathlib import Path

from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.hogai.session_summaries.session.stringify import SingleSessionSummaryStringifier
from ee.hogai.session_summaries.session_group.patterns import EnrichedSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.session_group.stringify import SessionGroupSummaryStringifier


def test_stringify_single_session_summary():
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
    assert stringified_data == output_data


def test_stringify_group_session_summary():
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
    assert stringified_data == output_data
