import json

from posthog.test.base import APIBaseTest

from ee.session_recordings.session_summary.patterns.output_data import (
    EnrichedSessionGroupSummaryPatternsList,
    EnrichedSessionGroupSummaryPattern,
    EnrichedSessionGroupSummaryPatternStats,
    PatternAssignedEventSegmentContext,
    EnrichedPatternAssignedEvent,
)
from posthog.temporal.ai.session_summary.activities.notebook import (
    create_summary_notebook,
    _generate_notebook_content_from_summary,
)

# TODO: Move to a proper directory


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

        notebook = create_summary_notebook(session_ids, self.user, self.team, summary_data, "TestDomain")

        # Verify the notebook was created
        self.assertIsNotNone(notebook)
        self.assertEqual(notebook.team, self.team)
        self.assertEqual(notebook.created_by, self.user)
        self.assertEqual(notebook.last_modified_by, self.user)
        self.assertIn("Session Summaries Report - TestDomain", notebook.title)

        # Check content structure
        content = notebook.content
        self.assertEqual(content["type"], "doc")
        self.assertGreater(len(content["content"]), 2)  # Should have more content with summary data

        # Check that it has the expected structure
        self.assertEqual(content["content"][0]["type"], "heading")
        self.assertIn("Session Summaries Report - TestDomain", content["content"][0]["content"][0]["text"])

        # Check that pattern content is included
        content_text = json.dumps(content)
        self.assertIn("Login API Failures", content_text)
        self.assertIn("critical", content_text)
        self.assertIn("TestDomain", content_text)

    def test_content_generation_function(self):
        """Test the content generation function directly"""

        session_ids = ["session_1", "session_2"]
        summary_data = self.create_test_summary_data()

        content = _generate_notebook_content_from_summary(summary_data, session_ids, "TestDomain")

        # Check basic structure
        self.assertEqual(content["type"], "doc")
        self.assertIsInstance(content["content"], list)
        self.assertGreater(len(content["content"]), 0)

        # Check that patterns are included
        content_text = json.dumps(content)
        self.assertIn("Login API Failures", content_text)
        self.assertIn("critical", content_text)
        self.assertIn("TestDomain", content_text)
        self.assertIn("Issues to review", content_text)
        self.assertIn("How we detect this", content_text)
        self.assertIn("Examples", content_text)

    def test_empty_patterns_handling(self):
        """Test handling of empty patterns"""

        session_ids = ["session_1"]
        empty_summary = EnrichedSessionGroupSummaryPatternsList(patterns=[])

        content = _generate_notebook_content_from_summary(empty_summary, session_ids, "TestDomain")

        # Should still create valid content
        self.assertEqual(content["type"], "doc")
        self.assertEqual(len(content["content"]), 3)

        content_text = json.dumps(content)
        self.assertIn("No patterns found", content_text)
        self.assertIn("TestDomain", content_text)

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

        content = _generate_notebook_content_from_summary(summary_data, session_ids, "TestDomain")

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
        content = _generate_notebook_content_from_summary(summary_data, session_ids, "TestDomain")

        # Check that patterns appear in correct order: critical, high, medium, low
        content_text = json.dumps(content)
        critical_pos = content_text.find("Pattern critical")
        high_pos = content_text.find("Pattern high")
        medium_pos = content_text.find("Pattern medium")
        low_pos = content_text.find("Pattern low")

        self.assertLess(critical_pos, high_pos)
        self.assertLess(high_pos, medium_pos)
        self.assertLess(medium_pos, low_pos)
