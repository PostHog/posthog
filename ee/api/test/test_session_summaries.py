import os
from unittest.mock import patch, MagicMock

from datetime import datetime
from posthog.test.base import APIBaseTest


class TestSessionSummariesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/environments/{self.team.id}/session_summaries/create_session_summaries/"

        # Mock environment requirements
        self.environment_patches = [
            patch("ee.api.session_summaries.is_cloud", return_value=True),
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
        ]
        for p in self.environment_patches:
            p.start()

    def tearDown(self):
        super().tearDown()
        for p in self.environment_patches:
            p.stop()

    def create_mock_result(self):
        """Create a mock result that mimics the serialized output"""
        # Return a dictionary that represents the serialized Pydantic model
        return {
            "patterns": [
                {
                    "pattern_id": 1,
                    "pattern_name": "Login Flow Pattern",
                    "pattern_description": "Users attempting to log in with some encountering errors",
                    "severity": "medium",
                    "indicators": ["login attempts", "form submissions"],
                    "events": [],
                    "stats": {
                        "occurences": 2,
                        "sessions_affected": 2,
                        "sessions_affected_ratio": 1.0,
                        "segments_success_ratio": 0.75,
                    },
                }
            ]
        }

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    @patch("ee.api.session_summaries.create_summary_notebook")
    def test_create_summaries_success(
        self, mock_create_notebook, mock_execute, mock_replay_events, mock_feature_enabled
    ):
        """Test successful creation of session summaries"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events_instance = MagicMock()
        mock_replay_events.return_value = mock_replay_events_instance
        # Mock sessions_found_with_timestamps to return found sessions with timestamps
        mock_replay_events_instance.sessions_found_with_timestamps.return_value = (
            {"session1", "session2"},
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )

        mock_result = self.create_mock_result()
        mock_execute.return_value = mock_result

        # Make request
        response = self.client.post(
            self.url,
            {"session_ids": ["session1", "session2"], "focus_area": "login process"},
            format="json",
        )

        # Assertions
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")

        data = response.json()
        # The response is the serialized EnrichedSessionGroupSummaryPatternsList
        self.assertIsInstance(data, dict)
        self.assertIn("patterns", data)
        self.assertEqual(len(data["patterns"]), 1)
        self.assertEqual(data["patterns"][0]["pattern_name"], "Login Flow Pattern")
        self.assertEqual(data["patterns"][0]["severity"], "medium")
        self.assertEqual(data["patterns"][0]["stats"]["occurences"], 2)

        # Verify execute_summarize_session_group was called correctly
        mock_execute.assert_called_once_with(
            session_ids=["session1", "session2"],
            user_id=self.user.pk,
            team=self.team,
            min_timestamp=datetime(2024, 1, 1, 10, 0, 0),
            max_timestamp=datetime(2024, 1, 1, 11, 0, 0),
            extra_summary_context=mock_execute.call_args[1]["extra_summary_context"],
            local_reads_prod=False,
        )
        # Check extra_summary_context separately
        self.assertEqual(mock_execute.call_args[1]["extra_summary_context"].focus_area, "login process")

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    @patch("ee.api.session_summaries.create_summary_notebook")
    def test_create_summaries_without_focus_area(
        self, mock_create_notebook, mock_execute, mock_replay_events, mock_feature_enabled
    ):
        """Test successful creation without focus area"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events_instance = MagicMock()
        mock_replay_events.return_value = mock_replay_events_instance
        # Mock sessions_found_with_timestamps to return found sessions with timestamps
        mock_replay_events_instance.sessions_found_with_timestamps.return_value = (
            {"session1", "session2"},
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )

        mock_result = self.create_mock_result()
        mock_execute.return_value = mock_result

        # Make request without focus_area
        response = self.client.post(
            self.url,
            {"session_ids": ["session1", "session2"]},
            format="json",
        )

        # Assertions
        self.assertEqual(response.status_code, 200)

        # Verify execute_summarize_session_group was called with None extra_context
        mock_execute.assert_called_once_with(
            session_ids=["session1", "session2"],
            user_id=self.user.pk,
            team=self.team,
            min_timestamp=datetime(2024, 1, 1, 10, 0, 0),
            max_timestamp=datetime(2024, 1, 1, 11, 0, 0),
            extra_summary_context=None,
            local_reads_prod=False,
        )

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    def test_create_summaries_missing_session_ids(self, mock_feature_enabled):
        """Test validation error when session_ids is missing"""
        mock_feature_enabled.return_value = True

        response = self.client.post(
            self.url,
            {"focus_area": "test"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertEqual(error["attr"], "session_ids")

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    def test_create_summaries_empty_session_ids(self, mock_feature_enabled):
        """Test validation error when session_ids is empty"""
        mock_feature_enabled.return_value = True

        response = self.client.post(
            self.url,
            {"session_ids": []},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertEqual(error["attr"], "session_ids")

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    def test_create_summaries_too_many_session_ids(self, mock_feature_enabled):
        """Test validation error when too many session_ids provided"""
        mock_feature_enabled.return_value = True
        session_ids = [f"session{i}" for i in range(55)]  # More than max of 50

        response = self.client.post(
            self.url,
            {"session_ids": session_ids},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertEqual(error["attr"], "session_ids")

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    def test_create_summaries_focus_area_too_long(self, mock_feature_enabled):
        """Test validation error when focus_area is too long"""
        mock_feature_enabled.return_value = True
        long_focus_area = "x" * 501  # More than max of 500

        response = self.client.post(
            self.url,
            {"session_ids": ["session1"], "focus_area": long_focus_area},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertEqual(error["attr"], "focus_area")

    def test_create_summaries_unauthenticated(self):
        """Test that unauthenticated requests are rejected"""
        self.client.logout()

        response = self.client.post(
            self.url,
            {"session_ids": ["session1"]},
            format="json",
        )

        self.assertEqual(response.status_code, 401)

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    def test_create_summaries_feature_disabled(self, mock_feature_enabled):
        """Test error when ai-session-summary feature is disabled"""
        mock_feature_enabled.return_value = False

        response = self.client.post(
            self.url,
            {"session_ids": ["session1"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertIn("Session summaries are not enabled", str(error))

    @patch("ee.api.session_summaries.is_cloud")
    def test_create_summaries_not_cloud(self, mock_is_cloud):
        """Test error when not in cloud environment"""
        mock_is_cloud.return_value = False

        response = self.client.post(
            self.url,
            {"session_ids": ["session1"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertIn("Session summaries are only supported in PostHog Cloud", str(error))

    @patch.dict(os.environ, {}, clear=True)  # Remove OPENAI_API_KEY
    def test_create_summaries_no_openai_key(self):
        """Test error when OPENAI_API_KEY is not set"""
        response = self.client.post(
            self.url,
            {"session_ids": ["session1"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertIn("Session summaries are only supported in PostHog Cloud", str(error))

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    def test_create_summaries_session_not_found(self, mock_replay_events, mock_feature_enabled):
        """Test error when session doesn't exist or doesn't belong to team"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events_instance = MagicMock()
        mock_replay_events.return_value = mock_replay_events_instance
        # Mock sessions_found_with_timestamps to return no sessions found
        mock_replay_events_instance.sessions_found_with_timestamps.return_value = (
            set(),  # Empty set means no sessions found
            None,
            None,
        )

        response = self.client.post(
            self.url,
            {"session_ids": ["nonexistent_session"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertIn("Sessions not found or do not belong to this team: nonexistent_session", str(error))

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    def test_create_summaries_mixed_session_existence(self, mock_replay_events, mock_feature_enabled):
        """Test error when some sessions exist and some don't"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events_instance = MagicMock()
        mock_replay_events.return_value = mock_replay_events_instance
        # Only session1 exists, session2 does not
        mock_replay_events_instance.sessions_found_with_timestamps.return_value = (
            {"session1"},  # Only session1 found
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )

        response = self.client.post(
            self.url,
            {"session_ids": ["session1", "session2"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()
        self.assertIn("Sessions not found or do not belong to this team: session2", str(error))

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    @patch("ee.api.session_summaries.create_summary_notebook")
    def test_create_summaries_execution_failure(
        self, mock_create_notebook, mock_execute, mock_replay_events, mock_feature_enabled
    ):
        """Test handling of execution failures"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events_instance = MagicMock()
        mock_replay_events.return_value = mock_replay_events_instance
        # Mock sessions_found_with_timestamps to return found sessions with timestamps
        mock_replay_events_instance.sessions_found_with_timestamps.return_value = (
            {"session1"},
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )

        # Mock execution failure
        mock_execute.side_effect = Exception("Workflow execution failed")

        response = self.client.post(
            self.url,
            {"session_ids": ["session1"]},
            format="json",
        )

        self.assertEqual(response.status_code, 500)
        error = response.json()
        self.assertIn("Failed to generate session summaries", str(error))

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    def test_create_summaries_validates_all_sessions_before_execution(
        self, mock_execute, mock_replay_events, mock_feature_enabled
    ):
        """Test that all sessions are validated before execution starts"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events_instance = MagicMock()
        mock_replay_events.return_value = mock_replay_events_instance
        # Only session1 and session2 exist, session3 does not
        mock_replay_events_instance.sessions_found_with_timestamps.return_value = (
            {"session1", "session2"},  # session3 not found
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )

        response = self.client.post(
            self.url,
            {"session_ids": ["session1", "session2", "session3"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        # Execution should never be called due to validation failure
        mock_execute.assert_not_called()

    def test_wrong_http_method(self):
        """Test that only POST is allowed"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)  # Method Not Allowed

        response = self.client.put(self.url, {})
        self.assertEqual(response.status_code, 405)

        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 405)

    @patch("ee.api.session_summaries.posthoganalytics.feature_enabled")
    @patch("ee.api.session_summaries.SessionReplayEvents")
    @patch("ee.api.session_summaries.execute_summarize_session_group")
    @patch("ee.api.session_summaries.create_summary_notebook")
    def test_create_summaries_single_session(
        self, mock_create_notebook, mock_execute, mock_replay_events, mock_feature_enabled
    ):
        """Test that single session works correctly"""
        # Setup mocks
        mock_feature_enabled.return_value = True
        mock_replay_events_instance = MagicMock()
        mock_replay_events.return_value = mock_replay_events_instance
        # Mock sessions_found_with_timestamps to return found sessions with timestamps
        mock_replay_events_instance.sessions_found_with_timestamps.return_value = (
            {"single_session"},
            datetime(2024, 1, 1, 10, 0, 0),
            datetime(2024, 1, 1, 11, 0, 0),
        )

        mock_result = self.create_mock_result()
        mock_execute.return_value = mock_result

        response = self.client.post(
            self.url,
            {"session_ids": ["single_session"]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        # Verify session validation was called once
        mock_replay_events_instance.sessions_found_with_timestamps.assert_called_once_with(
            ["single_session"], self.team
        )
