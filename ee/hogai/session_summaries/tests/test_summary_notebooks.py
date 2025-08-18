import json
from typing import Any

from posthog.test.base import APIBaseTest

from ee.hogai.session_summaries.session_group.patterns import (
    EnrichedSessionGroupSummaryPatternsList,
    EnrichedSessionGroupSummaryPattern,
    EnrichedSessionGroupSummaryPatternStats,
    PatternAssignedEventSegmentContext,
    EnrichedPatternAssignedEvent,
    RawSessionGroupSummaryPattern,
)
from ee.hogai.session_summaries.session_group.summary_notebooks import (
    create_notebook_from_summary,
    _generate_notebook_content_from_summary,
    format_single_sessions_status,
    format_extracted_patterns_status,
    NotebookIntermediateState,
)
from posthog.models.notebook.util import create_task_list


class TestNotebookCreation(APIBaseTest):
    def create_test_event(self) -> EnrichedPatternAssignedEvent:
        """Create a test event for reuse across tests."""
        return EnrichedPatternAssignedEvent(
            event_id="c517a10d",
            event_uuid="01980e4e-bfd8-700b-975a-a4418d470e3a",
            session_id="01980e4e-b64d-75ca-98d1-869dcfa9941d",
            description="API error (Non-OK response) stopped login",
            abandonment=False,
            confusion=False,
            exception="blocking",
            timestamp="2025-07-15T13:38:18.715000+00:00",
            milliseconds_since_start=2406,
            window_id="01980e4e-b64d-75ca-98d1-869eda822a9d",
            current_url="http://localhost:8010/login?next=/",
            event="$exception",
            event_type=None,
            event_index=4,
        )

    def create_segment_context(self, test_event: EnrichedPatternAssignedEvent) -> PatternAssignedEventSegmentContext:
        """Create a segment context for reuse across tests."""
        return PatternAssignedEventSegmentContext(
            segment_name="Repeated login attempts with server errors",
            segment_outcome="Two consecutive login submissions failed due to blocking API errors, causing user frustration",
            segment_success=False,
            segment_index=0,
            previous_events_in_segment=[],
            target_event=test_event,
            next_events_in_segment=[],
        )

    def create_pattern_stats(self) -> EnrichedSessionGroupSummaryPatternStats:
        """Create pattern stats for reuse across tests."""
        return EnrichedSessionGroupSummaryPatternStats(
            occurences=5,
            sessions_affected=2,
            sessions_affected_ratio=1.0,
            segments_success_ratio=0.0,
        )

    def create_test_pattern(
        self,
        segment_context: PatternAssignedEventSegmentContext,
        pattern_stats: EnrichedSessionGroupSummaryPatternStats,
    ) -> EnrichedSessionGroupSummaryPattern:
        """Create a test pattern for reuse across tests."""
        return EnrichedSessionGroupSummaryPattern(
            pattern_id=1,
            pattern_name="Login API Failures",
            pattern_description='Server-side errors ("Non-OK response" and "client_request_failure") occur immediately after users submit the login form, completely blocking authentication and preventing any conversion.',
            severity="critical",
            indicators=[
                "Blocking '$exception' events fired right after login submissions",
                "'client_request_failure' events associated with POST /login requests",
                "Multiple failures recorded inside a single login segment",
                "Session outcome flagged unsuccessful due to server errors",
            ],
            events=[segment_context],
            stats=pattern_stats,
        )

    def create_summary_data(self) -> EnrichedSessionGroupSummaryPatternsList:
        """Create summary data for reuse across tests."""
        test_event = self.create_test_event()
        segment_context = self.create_segment_context(test_event)
        pattern_stats = self.create_pattern_stats()
        test_pattern = self.create_test_pattern(segment_context, pattern_stats)
        return EnrichedSessionGroupSummaryPatternsList(patterns=[test_pattern])

    async def test_notebook_creation_with_summary_data(self) -> None:
        summary_data = self.create_summary_data()
        session_ids: list[str] = ["session_1", "session_2"]

        notebook = await create_notebook_from_summary(session_ids, self.user, self.team, summary_data)

        # Verify the notebook was created
        assert notebook is not None
        assert notebook.team == self.team
        assert notebook.created_by == self.user
        assert notebook.last_modified_by == self.user
        assert notebook.title is not None
        assert f"Session Summaries Report - {self.team.name}" in notebook.title

        # Check content structure
        content: dict[str, Any] = notebook.content
        assert content["type"] == "doc"
        assert len(content["content"]) > 2  # Should have more content with summary data

        # Check that it has the expected structure
        assert content["content"][0]["type"] == "heading"
        assert f"Session Summaries Report - {self.team.name}" in content["content"][0]["content"][0]["text"]

        # Check that pattern content is included
        content_text: str = json.dumps(content)
        assert "Login API Failures" in content_text
        assert "critical" in content_text
        assert self.team.name in content_text

    def test_content_generation_function(self) -> None:
        summary_data = self.create_summary_data()
        session_ids: list[str] = ["session_1", "session_2"]

        content: dict[str, Any] = _generate_notebook_content_from_summary(
            summary_data, session_ids, self.team.name, self.team.id
        )

        # Check basic structure
        assert content["type"] == "doc"
        assert isinstance(content["content"], list)
        assert len(content["content"]) > 0

        # Check that patterns are included
        content_text: str = json.dumps(content)
        assert "Login API Failures" in content_text
        assert "critical" in content_text
        assert self.team.name in content_text
        assert "Issues to review" in content_text
        assert "How we detect this" in content_text
        assert "Examples" in content_text

    def test_empty_patterns_handling(self) -> None:
        session_ids: list[str] = ["session_1"]
        empty_summary = EnrichedSessionGroupSummaryPatternsList(patterns=[])

        content: dict[str, Any] = _generate_notebook_content_from_summary(
            empty_summary, session_ids, self.team.name, self.team.id
        )

        # Should still create valid content
        assert content["type"] == "doc"
        assert len(content["content"]) == 4

        content_text: str = json.dumps(content)
        assert "No patterns found" in content_text
        assert self.team.name in content_text

    def test_pattern_with_multiple_examples(self) -> None:
        summary_data = self.create_summary_data()
        session_ids: list[str] = ["session_1", "session_2"]

        # Add more events to test the "3 examples limit" logic
        test_event_2 = EnrichedPatternAssignedEvent(
            event_id="c517a10e",
            event_uuid="01980e4e-bfd8-700b-975a-a4418d470e3b",
            session_id="01980e4e-b64d-75ca-98d1-869dcfa9941e",
            description="Second API error",
            abandonment=False,
            confusion=True,
            exception="blocking",
            timestamp="2025-07-15T13:38:19.715000+00:00",
            milliseconds_since_start=2500,
            window_id="01980e4e-b64d-75ca-98d1-869eda822a9d",
            current_url="http://localhost:8010/login?next=/",
            event="$exception",
            event_type=None,
            event_index=5,
        )

        segment_context_2 = PatternAssignedEventSegmentContext(
            segment_name="Another failed login",
            segment_outcome="Another failure",
            segment_success=False,
            segment_index=1,
            previous_events_in_segment=[],
            target_event=test_event_2,
            next_events_in_segment=[],
        )

        # Add the second event to the pattern
        summary_data.patterns[0].events.append(segment_context_2)

        content: dict[str, Any] = _generate_notebook_content_from_summary(
            summary_data, session_ids, self.team.name, self.team.id
        )

        # Should contain both examples
        content_text: str = json.dumps(content)
        assert "01980e4e-b64d-75ca-98d1-869dcfa9941d" in content_text
        assert "01980e4e-b64d-75ca-98d1-869dcfa9941e" in content_text
        assert "Repeated login attempts" in content_text
        assert "Another failed login" in content_text

    def test_severity_sorting(self) -> None:
        session_ids: list[str] = ["session_1"]

        # Create patterns with different severities
        patterns: list[EnrichedSessionGroupSummaryPattern] = []
        for i, severity in enumerate(["medium", "critical", "high", "low"]):
            test_event = EnrichedPatternAssignedEvent(
                event_id=f"event_{i}",
                event_uuid=f"uuid_{i}",
                session_id=f"session_{i}",
                description=f"Event {i}",
                abandonment=False,
                confusion=False,
                exception=None,
                timestamp="2025-07-15T13:38:18.715000+00:00",
                milliseconds_since_start=2406,
                window_id="window_id",
                current_url="http://localhost:8010/",
                event="$event",
                event_type=None,
                event_index=i,
            )

            segment_context = PatternAssignedEventSegmentContext(
                segment_name=f"Segment {i}",
                segment_outcome=f"Outcome {i}",
                segment_success=False,
                segment_index=i,
                previous_events_in_segment=[],
                target_event=test_event,
                next_events_in_segment=[],
            )

            pattern_stats = EnrichedSessionGroupSummaryPatternStats(
                occurences=1,
                sessions_affected=1,
                sessions_affected_ratio=1.0,
                segments_success_ratio=0.0,
            )

            pattern = EnrichedSessionGroupSummaryPattern(
                pattern_id=i + 1,
                pattern_name=f"Pattern {severity}",
                pattern_description=f"Pattern with {severity} severity",
                severity=severity,
                indicators=[f"Indicator for {severity}"],
                events=[segment_context],
                stats=pattern_stats,
            )
            patterns.append(pattern)

        summary_data = EnrichedSessionGroupSummaryPatternsList(patterns=patterns)
        content: dict[str, Any] = _generate_notebook_content_from_summary(
            summary_data, session_ids, self.team.name, self.team.id
        )

        # Check that patterns appear in correct order: critical, high, medium, low
        content_text: str = json.dumps(content)
        critical_pos: int = content_text.find("Pattern critical")
        high_pos: int = content_text.find("Pattern high")
        medium_pos: int = content_text.find("Pattern medium")
        low_pos: int = content_text.find("Pattern low")

        assert critical_pos < high_pos
        assert high_pos < medium_pos
        assert medium_pos < low_pos

    def test_nested_list_structure(self) -> None:
        # Create previous events
        prev_event_1 = EnrichedPatternAssignedEvent(
            event_id="prev_1",
            event_uuid="prev_uuid_1",
            session_id="test_session",
            description="Entered email into login form",
            abandonment=False,
            confusion=False,
            exception=None,
            timestamp="2025-07-15T13:38:17.715000+00:00",
            milliseconds_since_start=2000,
            window_id="window_id",
            current_url="http://localhost:8010/login",
            event="$autocapture",
            event_type=None,
            event_index=1,
        )

        prev_event_2 = EnrichedPatternAssignedEvent(
            event_id="prev_2",
            event_uuid="prev_uuid_2",
            session_id="test_session",
            description="Clicked submit button",
            abandonment=False,
            confusion=False,
            exception=None,
            timestamp="2025-07-15T13:38:18.000000+00:00",
            milliseconds_since_start=2300,
            window_id="window_id",
            current_url="http://localhost:8010/login",
            event="$autocapture",
            event_type=None,
            event_index=2,
        )

        # Create next events
        next_event_1 = EnrichedPatternAssignedEvent(
            event_id="next_1",
            event_uuid="next_uuid_1",
            session_id="test_session",
            description="Clicked Log in despite prior error",
            abandonment=False,
            confusion=True,
            exception=None,
            timestamp="2025-07-15T13:38:19.715000+00:00",
            milliseconds_since_start=3000,
            window_id="window_id",
            current_url="http://localhost:8010/login",
            event="$autocapture",
            event_type=None,
            event_index=4,
        )

        # Create target event
        target_event = EnrichedPatternAssignedEvent(
            event_id="target_1",
            event_uuid="target_uuid_1",
            session_id="test_session",
            description="API request failed; toast error shown",
            abandonment=False,
            confusion=False,
            exception="blocking",
            timestamp="2025-07-15T13:38:18.715000+00:00",
            milliseconds_since_start=2500,
            window_id="window_id",
            current_url="http://localhost:8010/login",
            event="$exception",
            event_type=None,
            event_index=3,
        )

        # Create segment context with nested events
        segment_context = PatternAssignedEventSegmentContext(
            segment_name="Initial login attempt with server error",
            segment_outcome="User's first login was blocked by server error toast",
            segment_success=False,
            segment_index=0,
            previous_events_in_segment=[prev_event_1, prev_event_2],
            target_event=target_event,
            next_events_in_segment=[next_event_1],
        )

        # Create pattern stats
        pattern_stats = EnrichedSessionGroupSummaryPatternStats(
            occurences=1,
            sessions_affected=1,
            sessions_affected_ratio=1.0,
            segments_success_ratio=0.0,
        )

        # Create pattern
        pattern = EnrichedSessionGroupSummaryPattern(
            pattern_id=1,
            pattern_name="Test Nested Pattern",
            pattern_description="Test pattern with nested events",
            severity="critical",
            indicators=["Test indicator"],
            events=[segment_context],
            stats=pattern_stats,
        )

        summary_data = EnrichedSessionGroupSummaryPatternsList(patterns=[pattern])
        content: dict[str, Any] = _generate_notebook_content_from_summary(
            summary_data, ["test_session"], self.team.name, self.team.id
        )

        # Find the outcome section in the content
        content_json: str = json.dumps(content, indent=2)

        # Verify the nested structure exists
        assert "What happened before:" in content_json
        assert "What happened after:" in content_json
        assert "Entered email into login form" in content_json
        assert "Clicked submit button" in content_json
        assert "Clicked Log in despite prior error" in content_json

        # Verify proper bullet list structure
        # Check that we have nested bulletList structures
        assert "bulletList" in content_json

        # Parse the content and verify the structure
        outcome_section_found: bool = False
        for content_item in content["content"]:
            if content_item.get("type") == "bulletList":
                # Look for list items with nested content
                for list_item in content_item.get("content", []):
                    if list_item.get("type") == "listItem":
                        list_content: list[dict[str, Any]] = list_item.get("content", [])
                        # Check if this list item has both paragraph and nested bulletList
                        has_paragraph: bool = any(item.get("type") == "paragraph" for item in list_content)
                        has_nested_bullet_list: bool = any(item.get("type") == "bulletList" for item in list_content)

                        if has_paragraph and has_nested_bullet_list:
                            outcome_section_found = True
                            # Verify the nested structure contains our test data
                            nested_content: str = json.dumps(list_content)
                            if "What happened before:" in nested_content or "What happened after:" in nested_content:
                                # Found the nested structure we're testing
                                break

        assert outcome_section_found, "Nested list structure with paragraph and bulletList not found"

    def test_replay_link_includes_timestamp(self) -> None:
        # Create a test event with specific milliseconds_since_start
        test_event = EnrichedPatternAssignedEvent(
            event_id="test_event_id",
            event_uuid="test_event_uuid",
            session_id="test_session_id",
            description="Test event",
            abandonment=False,
            confusion=False,
            exception=None,
            timestamp="2025-07-15T13:38:18.715000+00:00",
            milliseconds_since_start=5500,  # This should result in t=5
            window_id="test_window_id",
            current_url="http://localhost:8010/test",
            event="$pageview",
            event_type=None,
            event_index=1,
        )

        # Create segment context
        segment_context = PatternAssignedEventSegmentContext(
            segment_name="Test segment",
            segment_outcome="Test outcome",
            segment_success=True,
            segment_index=0,
            previous_events_in_segment=[],
            target_event=test_event,
            next_events_in_segment=[],
        )

        # Create pattern stats
        pattern_stats = EnrichedSessionGroupSummaryPatternStats(
            occurences=1,
            sessions_affected=1,
            sessions_affected_ratio=1.0,
            segments_success_ratio=1.0,
        )

        # Create pattern
        pattern = EnrichedSessionGroupSummaryPattern(
            pattern_id=1,
            pattern_name="Test Pattern",
            pattern_description="Test pattern for replay link",
            severity="low",
            indicators=["Test indicator"],
            events=[segment_context],
            stats=pattern_stats,
        )

        summary_data = EnrichedSessionGroupSummaryPatternsList(patterns=[pattern])
        content: dict[str, Any] = _generate_notebook_content_from_summary(
            summary_data, ["test_session_id"], self.team.name, self.team.id
        )

        # Convert content to JSON string to search for the replay link
        content_text: str = json.dumps(content)

        # Check that the replay link includes the timestamp parameter
        assert f"/project/{self.team.id}/replay/test_session_id?t=5" in content_text

        # Test with different milliseconds_since_start values
        test_cases: list[tuple[int, int]] = [
            (1000, 1),  # 1 second
            (1500, 1),  # 1.5 seconds -> 1
            (2999, 2),  # 2.999 seconds -> 2
            (10000, 10),  # 10 seconds
            (0, 0),  # 0 seconds
        ]

        for millis, expected_timestamp in test_cases:
            # Create new instances for each test case since dataclasses are frozen
            test_event_case = EnrichedPatternAssignedEvent(
                event_id="test_event_id",
                event_uuid="test_event_uuid",
                session_id="test_session_id",
                description="Test event",
                abandonment=False,
                confusion=False,
                exception=None,
                timestamp="2025-07-15T13:38:18.715000+00:00",
                milliseconds_since_start=millis,
                window_id="test_window_id",
                current_url="http://localhost:8010/test",
                event="$pageview",
                event_type=None,
                event_index=1,
            )

            segment_context_case = PatternAssignedEventSegmentContext(
                segment_name="Test segment",
                segment_outcome="Test outcome",
                segment_success=True,
                segment_index=0,
                previous_events_in_segment=[],
                target_event=test_event_case,
                next_events_in_segment=[],
            )

            pattern.events = [segment_context_case]
            content = _generate_notebook_content_from_summary(
                summary_data, ["test_session_id"], self.team.name, self.team.id
            )
            content_text = json.dumps(content)
            assert (
                f"/project/{self.team.id}/replay/test_session_id?t={expected_timestamp}" in content_text
            ), f"Failed for {millis}ms -> t={expected_timestamp}"

    def test_format_single_sessions_status_empty(self) -> None:
        result: dict[str, Any] = format_single_sessions_status({})
        assert result["type"] == "doc"
        assert len(result["content"]) == 2  # heading + bullet list
        # Check heading
        assert result["content"][0]["type"] == "heading"
        assert result["content"][0]["attrs"]["level"] == 2
        assert result["content"][0]["content"][0]["text"] == "Session Processing Status"
        # Check empty bullet list
        assert result["content"][1]["type"] == "bulletList"
        assert result["content"][1]["content"] == []

    def test_format_single_sessions_status_all_pending(self) -> None:
        sessions_status: dict[str, bool] = {
            "session-1": False,
            "session-2": False,
            "session-3": False,
        }
        result: dict[str, Any] = format_single_sessions_status(sessions_status)
        # Check structure
        assert result["type"] == "doc"
        assert len(result["content"]) == 2  # heading + bullet list
        # Check heading
        assert result["content"][0]["type"] == "heading"
        assert result["content"][0]["content"][0]["text"] == "Session Processing Status"
        # Check bullet list
        bullet_list: dict[str, Any] = result["content"][1]
        assert bullet_list["type"] == "bulletList"
        assert len(bullet_list["content"]) == 3
        # Check each item
        for i, (session_id, _) in enumerate(sessions_status.items()):
            list_item: dict[str, Any] = bullet_list["content"][i]
            assert list_item["type"] == "listItem"
            paragraph: dict[str, Any] = list_item["content"][0]
            assert paragraph["type"] == "paragraph"
            text: dict[str, Any] = paragraph["content"][0]
            assert text["type"] == "text"
            assert text["text"] == f"{session_id} ❌"

    def test_format_single_sessions_status_mixed(self) -> None:
        sessions_status: dict[str, bool] = {
            "session-1": True,
            "session-2": False,
            "session-3": True,
            "session-4": False,
        }
        result: dict[str, Any] = format_single_sessions_status(sessions_status)
        # Check structure
        assert result["type"] == "doc"
        assert len(result["content"]) == 2  # heading + bullet list
        # Check heading
        assert result["content"][0]["type"] == "heading"
        assert result["content"][0]["content"][0]["text"] == "Session Processing Status"
        # Check bullet list
        bullet_list: dict[str, Any] = result["content"][1]
        assert bullet_list["type"] == "bulletList"
        assert len(bullet_list["content"]) == 4
        # Check each item
        for i, (session_id, is_completed) in enumerate(sessions_status.items()):
            list_item: dict[str, Any] = bullet_list["content"][i]
            assert list_item["type"] == "listItem"
            paragraph: dict[str, Any] = list_item["content"][0]
            assert paragraph["type"] == "paragraph"
            text: dict[str, Any] = paragraph["content"][0]
            assert text["type"] == "text"
            emoji: str = "✅" if is_completed else "❌"
            assert text["text"] == f"{session_id} {emoji}"

    def test_format_single_sessions_status_all_completed(self) -> None:
        sessions_status: dict[str, bool] = {
            "session-1": True,
            "session-2": True,
            "session-3": True,
        }
        result: dict[str, Any] = format_single_sessions_status(sessions_status)
        # Check structure
        assert result["type"] == "doc"
        assert len(result["content"]) == 2  # heading + bullet list
        # Check heading
        assert result["content"][0]["type"] == "heading"
        assert result["content"][0]["content"][0]["text"] == "Session Processing Status"
        # Check bullet list
        bullet_list: dict[str, Any] = result["content"][1]
        assert bullet_list["type"] == "bulletList"
        assert len(bullet_list["content"]) == 3
        # Check each item
        for i, (session_id, _) in enumerate(sessions_status.items()):
            list_item: dict[str, Any] = bullet_list["content"][i]
            assert list_item["type"] == "listItem"
            paragraph: dict[str, Any] = list_item["content"][0]
            assert paragraph["type"] == "paragraph"
            text: dict[str, Any] = paragraph["content"][0]
            assert text["type"] == "text"
            assert text["text"] == f"{session_id} ✅"

    def test_format_single_sessions_status_single_session(self) -> None:
        sessions_status: dict[str, bool] = {"single-session": True}
        result: dict[str, Any] = format_single_sessions_status(sessions_status)
        # Check structure
        assert result["type"] == "doc"
        assert len(result["content"]) == 2  # heading + bullet list
        # Check heading
        assert result["content"][0]["type"] == "heading"
        assert result["content"][0]["content"][0]["text"] == "Session Processing Status"
        # Check bullet list
        bullet_list: dict[str, Any] = result["content"][1]
        assert bullet_list["type"] == "bulletList"
        assert len(bullet_list["content"]) == 1
        # Check the single item
        list_item: dict[str, Any] = bullet_list["content"][0]
        assert list_item["type"] == "listItem"
        paragraph: dict[str, Any] = list_item["content"][0]
        assert paragraph["type"] == "paragraph"
        text: dict[str, Any] = paragraph["content"][0]
        assert text["type"] == "text"
        assert text["text"] == "single-session ✅"

    def test_format_extracted_patterns_status_empty(self) -> None:
        result: dict[str, Any] = format_extracted_patterns_status([])
        assert result["type"] == "doc"
        assert len(result["content"]) == 2  # heading + message
        # Check heading
        assert result["content"][0]["type"] == "heading"
        assert result["content"][0]["attrs"]["level"] == 2
        assert result["content"][0]["content"][0]["text"] == "Extracted Patterns"
        # Check empty message
        assert result["content"][1]["type"] == "paragraph"
        assert "No patterns extracted yet" in str(result["content"][1])

    def test_format_extracted_patterns_status_with_patterns(self) -> None:
        patterns: list[RawSessionGroupSummaryPattern] = [
            RawSessionGroupSummaryPattern(
                pattern_id=1,
                pattern_name="Login Flow Issues",
                pattern_description="Users experiencing difficulties during login",
                severity="high",
                indicators=["multiple login attempts", "error messages", "password reset"],
            ),
            RawSessionGroupSummaryPattern(
                pattern_id=2,
                pattern_name="Navigation Confusion",
                pattern_description="Users getting lost in navigation",
                severity="medium",
                indicators=["back button usage", "repeated page visits"],
            ),
        ]

        result: dict[str, Any] = format_extracted_patterns_status(patterns)
        # Check structure
        assert result["type"] == "doc"
        assert len(result["content"]) == 2  # heading + bullet list
        # Check heading
        assert result["content"][0]["type"] == "heading"
        assert result["content"][0]["content"][0]["text"] == "Extracted Patterns"
        # Check bullet list
        bullet_list: dict[str, Any] = result["content"][1]
        assert bullet_list["type"] == "bulletList"
        assert len(bullet_list["content"]) == 2  # Two patterns

        # Check first pattern
        first_item: dict[str, Any] = bullet_list["content"][0]
        assert first_item["type"] == "listItem"
        assert len(first_item["content"]) == 3  # header, description, indicators

        # Verify pattern content includes name and severity
        first_header: dict[str, Any] = first_item["content"][0]
        assert first_header["type"] == "paragraph"
        header_text: str = first_header["content"][0]["text"]
        assert "Login Flow Issues" in header_text
        assert "HIGH" in header_text  # Enum value is uppercase

    def test_format_extracted_patterns_status_with_minimal_indicators(self) -> None:
        patterns: list[RawSessionGroupSummaryPattern] = [
            RawSessionGroupSummaryPattern(
                pattern_id=1,
                pattern_name="Simple Pattern",
                pattern_description="A pattern with minimal indicators",
                severity="low",
                indicators=["Minimal indicator"],  # At least one indicator is required by the model
            )
        ]

        result: dict[str, Any] = format_extracted_patterns_status(patterns)
        # Check structure
        assert result["type"] == "doc"
        bullet_list: dict[str, Any] = result["content"][1]
        assert bullet_list["type"] == "bulletList"

        # Check pattern item has 3 parts: header, description, and indicators
        first_item: dict[str, Any] = bullet_list["content"][0]
        assert first_item["type"] == "listItem"
        assert len(first_item["content"]) == 3  # header, description, indicators


class TestTaskListUtilities(APIBaseTest):
    def test_create_task_list_empty(self) -> None:
        result: dict[str, Any] = create_task_list([])
        assert result["type"] == "bulletList"
        assert result["content"] == []

    def test_create_task_list_all_unchecked(self) -> None:
        items: list[tuple[str, bool]] = [
            ("Task 1", False),
            ("Task 2", False),
            ("Task 3", False),
        ]
        result: dict[str, Any] = create_task_list(items)
        assert result["type"] == "bulletList"
        assert len(result["content"]) == 3

        for i, (task_text, _) in enumerate(items):
            list_item: dict[str, Any] = result["content"][i]
            assert list_item["type"] == "listItem"
            paragraph: dict[str, Any] = list_item["content"][0]
            assert paragraph["type"] == "paragraph"
            text_content: dict[str, Any] = paragraph["content"][0]
            assert text_content["type"] == "text"
            assert text_content["text"] == f"[ ] {task_text}"

    def test_create_task_list_all_checked(self) -> None:
        items: list[tuple[str, bool]] = [
            ("Completed task 1", True),
            ("Completed task 2", True),
        ]
        result: dict[str, Any] = create_task_list(items)
        assert result["type"] == "bulletList"
        assert len(result["content"]) == 2

        for i, (task_text, _) in enumerate(items):
            list_item: dict[str, Any] = result["content"][i]
            text_content: dict[str, Any] = list_item["content"][0]["content"][0]
            assert text_content["text"] == f"[x] {task_text}"

    def test_create_task_list_mixed(self) -> None:
        items: list[tuple[str, bool]] = [
            ("First task", True),
            ("Second task", False),
            ("Third task", True),
            ("Fourth task", False),
        ]
        result: dict[str, Any] = create_task_list(items)
        assert result["type"] == "bulletList"
        assert len(result["content"]) == 4

        expected_prefixes: list[str] = ["[x]", "[ ]", "[x]", "[ ]"]
        for i, (task_text, _) in enumerate(items):
            list_item: dict[str, Any] = result["content"][i]
            text_content: dict[str, Any] = list_item["content"][0]["content"][0]
            assert text_content["text"] == f"{expected_prefixes[i]} {task_text}"


class TestNotebookIntermediateState(APIBaseTest):
    def test_initialization(self) -> None:
        state = NotebookIntermediateState(team_name="Test Team")

        assert state.team_name == "Test Team"
        assert len(state.plan_items) == 3
        assert state.plan_items[0] == ("Watch sessions", False)
        assert state.plan_items[1] == ("Find patterns", False)
        assert state.plan_items[2] == ("Generate final report", False)
        assert state.current_step_index == 0
        assert state.current_step_content is None
        assert state.completed_steps == []

    def test_update_step_progress(self) -> None:
        state = NotebookIntermediateState(team_name="Test Team")

        test_content: dict[str, Any] = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Progress update"}]}],
        }
        state.update_step_progress(test_content)

        assert state.current_step_content == test_content

    def test_complete_current_step(self) -> None:
        state = NotebookIntermediateState(team_name="Test Team")

        # Set some progress content
        test_content: dict[str, Any] = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Step 1 content"}]}],
        }
        state.update_step_progress(test_content)

        # Complete the first step
        state.complete_current_step()

        # Check that the step is marked as completed
        assert state.plan_items[0] == ("Watch sessions", True)
        # Check that we moved to the next step
        assert state.current_step_index == 1
        # Check that current content is cleared
        assert state.current_step_content is None
        # Check that the completed step is preserved
        assert len(state.completed_steps) == 1
        assert state.completed_steps[0][0] == "Watch sessions"
        assert state.completed_steps[0][1] == test_content

    def test_complete_multiple_steps(self) -> None:
        state = NotebookIntermediateState(team_name="Test Team")

        # Complete first step
        content1: dict[str, Any] = {"type": "doc", "content": [{"type": "text", "text": "Sessions watched"}]}
        state.update_step_progress(content1)
        state.complete_current_step()

        # Complete second step
        content2: dict[str, Any] = {"type": "doc", "content": [{"type": "text", "text": "Patterns found"}]}
        state.update_step_progress(content2)
        state.complete_current_step()

        # Check state
        assert state.plan_items[0] == ("Watch sessions", True)
        assert state.plan_items[1] == ("Find patterns", True)
        assert state.plan_items[2] == ("Generate final report", False)
        assert state.current_step_index == 2
        assert len(state.completed_steps) == 2

        # Check completed steps are in correct order
        assert state.completed_steps[0][0] == "Watch sessions"
        assert state.completed_steps[1][0] == "Find patterns"

    def test_complete_step_without_content(self) -> None:
        state = NotebookIntermediateState(team_name="Test Team")

        # Complete without setting any content
        state.complete_current_step()

        # Should still mark as completed and move forward
        assert state.plan_items[0] == ("Watch sessions", True)
        assert state.current_step_index == 1
        # But no content should be preserved
        assert state.completed_steps == []

    def test_format_initial_state(self) -> None:
        state = NotebookIntermediateState(team_name="Test Team")

        formatted: dict[str, Any] = state.format_intermediate_state()

        assert formatted["type"] == "doc"
        content: list[dict[str, Any]] = formatted["content"]

        # Check main title
        assert content[0]["type"] == "heading"
        assert "Session Group Analysis - Test Team" in content[0]["content"][0]["text"]

        # Check plan section
        assert content[2]["type"] == "heading"
        assert content[2]["content"][0]["text"] == "Plan"

        # Check task list
        assert content[3]["type"] == "bulletList"
        task_list: list[dict[str, Any]] = content[3]["content"]
        assert len(task_list) == 3

        # All should be unchecked initially
        for item in task_list:
            text: str = item["content"][0]["content"][0]["text"]
            assert text.startswith("[ ]")

    def test_format_state_with_current_progress(self) -> None:
        state = NotebookIntermediateState(team_name="Test Team")

        # Add progress to current step
        progress_content: dict[str, Any] = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Session Processing Status"}],
                },
                {"type": "paragraph", "content": [{"type": "text", "text": "Processing session 1 of 5"}]},
            ],
        }
        state.update_step_progress(progress_content)

        formatted: dict[str, Any] = state.format_intermediate_state()
        content: list[dict[str, Any]] = formatted["content"]

        # Should have: title, empty, plan heading, task list, empty, progress heading, progress paragraph
        assert len(content) > 5

        # Find the progress content (should be after the task list)
        found_progress: bool = False
        for item in content:
            if item.get("type") == "heading" and item.get("content"):
                heading_text: str = item["content"][0].get("text", "")
                if "Session Processing Status" in heading_text:
                    found_progress = True
                    break

        assert found_progress, "Progress content not found in formatted output"

    def test_format_state_with_completed_steps(self) -> None:
        state = NotebookIntermediateState(team_name="Test Team")

        # Complete first step
        content1: dict[str, Any] = {
            "type": "doc",
            "content": [
                {"type": "heading", "content": [{"type": "text", "text": "Sessions Watched"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "All sessions processed"}]},
            ],
        }
        state.update_step_progress(content1)
        state.complete_current_step()

        # Add progress for second step
        content2: dict[str, Any] = {
            "type": "doc",
            "content": [
                {"type": "heading", "content": [{"type": "text", "text": "Finding Patterns"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Analyzing behaviors"}]},
            ],
        }
        state.update_step_progress(content2)

        formatted: dict[str, Any] = state.format_intermediate_state()
        content_str: str = json.dumps(formatted)

        # Check that first step is marked as completed in plan
        assert "[x] Watch sessions" in content_str
        assert "[ ] Find patterns" in content_str

        # Check that completed step appears with "Completed" marker
        assert "Step: Watch sessions (Completed)" in content_str
        assert "All sessions processed" in content_str

        # Check that current progress is shown
        assert "Analyzing behaviors" in content_str

    def test_format_state_completed_steps_reverse_order(self) -> None:
        state = NotebookIntermediateState(team_name="Test Team")

        # Complete two steps
        content1: dict[str, Any] = {"type": "doc", "content": [{"type": "text", "text": "First step done"}]}
        state.update_step_progress(content1)
        state.complete_current_step()

        content2: dict[str, Any] = {"type": "doc", "content": [{"type": "text", "text": "Second step done"}]}
        state.update_step_progress(content2)
        state.complete_current_step()

        formatted: dict[str, Any] = state.format_intermediate_state()
        content_str: str = json.dumps(formatted)

        # Find positions of completed step markers
        pos_first: int = content_str.find("Step: Watch sessions (Completed)")
        pos_second: int = content_str.find("Step: Find patterns (Completed)")

        # Second step should appear before first step (reverse order)
        assert pos_first > pos_second, "Completed steps should appear in reverse order"

    def test_complete_all_steps(self) -> None:
        state = NotebookIntermediateState(team_name="Test Team")

        # Complete all three steps
        for i in range(3):
            content: dict[str, Any] = {"type": "doc", "content": [{"type": "text", "text": f"Step {i+1} done"}]}
            state.update_step_progress(content)
            state.complete_current_step()

        # All should be marked as completed
        assert state.plan_items[0] == ("Watch sessions", True)
        assert state.plan_items[1] == ("Find patterns", True)
        assert state.plan_items[2] == ("Generate final report", True)
        assert state.current_step_index == 3
        assert len(state.completed_steps) == 3

    def test_e2e_workflow(self) -> None:
        state = NotebookIntermediateState(team_name="PostHog")

        # Initial state - just the plan
        initial_formatted: dict[str, Any] = state.format_intermediate_state()
        initial_str: str = json.dumps(initial_formatted)
        assert "Session Group Analysis - PostHog" in initial_str
        assert "[ ] Watch sessions" in initial_str
        assert "[ ] Find patterns" in initial_str
        assert "[ ] Generate final report" in initial_str

        # Step 1: Watching sessions
        sessions_status: dict[str, Any] = format_single_sessions_status(
            {
                "session-1": True,
                "session-2": False,
                "session-3": True,
            }
        )
        state.update_step_progress(sessions_status)

        step1_formatted: dict[str, Any] = state.format_intermediate_state()
        step1_str: str = json.dumps(step1_formatted)
        assert "Session Processing Status" in step1_str
        # Check the emojis appear in the JSON (they get escaped to unicode)
        assert "session-1" in step1_str
        assert "session-2" in step1_str
        assert "\\u2705" in step1_str  # ✅ emoji escaped in JSON
        assert "\\u274c" in step1_str  # ❌ emoji escaped in JSON

        # Complete step 1
        state.complete_current_step()

        # Step 2: Finding patterns
        patterns: list[RawSessionGroupSummaryPattern] = [
            RawSessionGroupSummaryPattern(
                pattern_id=1,
                pattern_name="Login Issues",
                pattern_description="Users having trouble logging in",
                severity="high",
                indicators=["multiple attempts", "errors"],
            )
        ]
        patterns_status: dict[str, Any] = format_extracted_patterns_status(patterns)
        state.update_step_progress(patterns_status)

        step2_formatted: dict[str, Any] = state.format_intermediate_state()
        step2_str: str = json.dumps(step2_formatted)
        assert "[x] Watch sessions" in step2_str
        assert "[ ] Find patterns" in step2_str
        assert "Extracted Patterns" in step2_str
        assert "Login Issues" in step2_str
        assert "Step: Watch sessions (Completed)" in step2_str

        # Complete step 2
        state.complete_current_step()

        # Step 3: Generating report
        report_progress: dict[str, Any] = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Generating final report..."}]}],
        }
        state.update_step_progress(report_progress)

        step3_formatted: dict[str, Any] = state.format_intermediate_state()
        step3_str: str = json.dumps(step3_formatted)
        assert "[x] Watch sessions" in step3_str
        assert "[x] Find patterns" in step3_str
        assert "[ ] Generate final report" in step3_str
        assert "Generating final report..." in step3_str
        assert "Step: Find patterns (Completed)" in step3_str
        assert "Step: Watch sessions (Completed)" in step3_str

        # Verify the order of completed steps (should be reverse)
        pos_patterns: int = step3_str.find("Step: Find patterns (Completed)")
        pos_sessions: int = step3_str.find("Step: Watch sessions (Completed)")
        assert pos_patterns < pos_sessions, "Most recent completed step should appear first"
