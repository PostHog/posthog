import json

from posthog.test.base import APIBaseTest

from ee.hogai.session_summaries.session_group.patterns import (
    EnrichedSessionGroupSummaryPatternsList,
    EnrichedSessionGroupSummaryPattern,
    EnrichedSessionGroupSummaryPatternStats,
    PatternAssignedEventSegmentContext,
    EnrichedPatternAssignedEvent,
)
from ee.hogai.session_summaries.session_group.summary_notebooks import (
    create_summary_notebook,
    _generate_notebook_content_from_summary,
)


class TestNotebookCreation(APIBaseTest):
    def create_test_summary_data(self):
        """Create test summary data that matches the example provided"""

        # Create a test event
        test_event = EnrichedPatternAssignedEvent(
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

        # Create segment context
        segment_context = PatternAssignedEventSegmentContext(
            segment_name="Repeated login attempts with server errors",
            segment_outcome="Two consecutive login submissions failed due to blocking API errors, causing user frustration",
            segment_success=False,
            segment_index=0,
            previous_events_in_segment=[],
            target_event=test_event,
            next_events_in_segment=[],
        )

        # Create pattern stats
        pattern_stats = EnrichedSessionGroupSummaryPatternStats(
            occurences=5,
            sessions_affected=2,
            sessions_affected_ratio=1.0,
            segments_success_ratio=0.0,
        )

        # Create pattern
        pattern = EnrichedSessionGroupSummaryPattern(
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

        return EnrichedSessionGroupSummaryPatternsList(patterns=[pattern])

    def test_notebook_creation_with_summary_data(self):
        """Test notebook creation with summary data"""

        session_ids = ["session_1", "session_2"]
        summary_data = self.create_test_summary_data()

        notebook = create_summary_notebook(session_ids, self.user, self.team, summary_data)

        # Verify the notebook was created
        self.assertIsNotNone(notebook)
        self.assertEqual(notebook.team, self.team)
        self.assertEqual(notebook.created_by, self.user)
        self.assertEqual(notebook.last_modified_by, self.user)
        assert notebook.title is not None
        self.assertIn(f"Session Summaries Report - {self.team.name}", notebook.title)

        # Check content structure
        content = notebook.content
        self.assertEqual(content["type"], "doc")
        self.assertGreater(len(content["content"]), 2)  # Should have more content with summary data

        # Check that it has the expected structure
        self.assertEqual(content["content"][0]["type"], "heading")
        self.assertIn(f"Session Summaries Report - {self.team.name}", content["content"][0]["content"][0]["text"])

        # Check that pattern content is included
        content_text = json.dumps(content)
        self.assertIn("Login API Failures", content_text)
        self.assertIn("critical", content_text)
        self.assertIn(self.team.name, content_text)

    def test_content_generation_function(self):
        """Test the content generation function directly"""

        session_ids = ["session_1", "session_2"]
        summary_data = self.create_test_summary_data()

        content = _generate_notebook_content_from_summary(summary_data, session_ids, self.team.name, self.team.id)

        # Check basic structure
        self.assertEqual(content["type"], "doc")
        self.assertIsInstance(content["content"], list)
        self.assertGreater(len(content["content"]), 0)

        # Check that patterns are included
        content_text = json.dumps(content)
        self.assertIn("Login API Failures", content_text)
        self.assertIn("critical", content_text)
        self.assertIn(self.team.name, content_text)
        self.assertIn("Issues to review", content_text)
        self.assertIn("How we detect this", content_text)
        self.assertIn("Examples", content_text)

    def test_empty_patterns_handling(self):
        """Test handling of empty patterns"""

        session_ids = ["session_1"]
        empty_summary = EnrichedSessionGroupSummaryPatternsList(patterns=[])

        content = _generate_notebook_content_from_summary(empty_summary, session_ids, self.team.name, self.team.id)

        # Should still create valid content
        self.assertEqual(content["type"], "doc")
        self.assertEqual(len(content["content"]), 4)

        content_text = json.dumps(content)
        self.assertIn("No patterns found", content_text)
        self.assertIn(self.team.name, content_text)

    def test_pattern_with_multiple_examples(self):
        """Test pattern with multiple examples to ensure proper handling"""

        session_ids = ["session_1", "session_2"]
        summary_data = self.create_test_summary_data()

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

        content = _generate_notebook_content_from_summary(summary_data, session_ids, self.team.name, self.team.id)

        # Should contain both examples
        content_text = json.dumps(content)
        self.assertIn("01980e4e-b64d-75ca-98d1-869dcfa9941d", content_text)
        self.assertIn("01980e4e-b64d-75ca-98d1-869dcfa9941e", content_text)
        self.assertIn("Repeated login attempts", content_text)
        self.assertIn("Another failed login", content_text)

    def test_severity_sorting(self):
        """Test that patterns are sorted by severity"""

        session_ids = ["session_1"]

        # Create patterns with different severities
        patterns = []
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
        content = _generate_notebook_content_from_summary(summary_data, session_ids, self.team.name, self.team.id)

        # Check that patterns appear in correct order: critical, high, medium, low
        content_text = json.dumps(content)
        critical_pos = content_text.find("Pattern critical")
        high_pos = content_text.find("Pattern high")
        medium_pos = content_text.find("Pattern medium")
        low_pos = content_text.find("Pattern low")

        self.assertLess(critical_pos, high_pos)
        self.assertLess(high_pos, medium_pos)
        self.assertLess(medium_pos, low_pos)

    def test_nested_list_structure(self):
        """Test that nested lists are properly structured for previous and next events"""

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
        content = _generate_notebook_content_from_summary(summary_data, ["test_session"], self.team.name, self.team.id)

        # Find the outcome section in the content
        content_json = json.dumps(content, indent=2)

        # Verify the nested structure exists
        self.assertIn("What happened before:", content_json)
        self.assertIn("What happened after:", content_json)
        self.assertIn("Entered email into login form", content_json)
        self.assertIn("Clicked submit button", content_json)
        self.assertIn("Clicked Log in despite prior error", content_json)

        # Verify proper bullet list structure
        # Check that we have nested bulletList structures
        self.assertIn("bulletList", content_json)

        # Parse the content and verify the structure
        outcome_section_found = False
        for content_item in content["content"]:
            if content_item.get("type") == "bulletList":
                # Look for list items with nested content
                for list_item in content_item.get("content", []):
                    if list_item.get("type") == "listItem":
                        list_content = list_item.get("content", [])
                        # Check if this list item has both paragraph and nested bulletList
                        has_paragraph = any(item.get("type") == "paragraph" for item in list_content)
                        has_nested_bullet_list = any(item.get("type") == "bulletList" for item in list_content)

                        if has_paragraph and has_nested_bullet_list:
                            outcome_section_found = True
                            # Verify the nested structure contains our test data
                            nested_content = json.dumps(list_content)
                            if "What happened before:" in nested_content or "What happened after:" in nested_content:
                                # Found the nested structure we're testing
                                break

        self.assertTrue(outcome_section_found, "Nested list structure with paragraph and bulletList not found")

    def test_replay_link_includes_timestamp(self):
        """Test that replay links include the timestamp parameter calculated from milliseconds_since_start"""

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
        content = _generate_notebook_content_from_summary(
            summary_data, ["test_session_id"], self.team.name, self.team.id
        )

        # Convert content to JSON string to search for the replay link
        content_text = json.dumps(content)

        # Check that the replay link includes the timestamp parameter
        self.assertIn(f"/project/{self.team.id}/replay/test_session_id?t=5", content_text)

        # Test with different milliseconds_since_start values
        test_cases = [
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
            self.assertIn(
                f"/project/{self.team.id}/replay/test_session_id?t={expected_timestamp}",
                content_text,
                f"Failed for {millis}ms -> t={expected_timestamp}",
            )
