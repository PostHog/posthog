from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized
from rest_framework import status

from ee.hogai.tools.replay.visually_analyze_session_segment import MAX_SEGMENT_DURATION_S, parse_timestamp_to_seconds


class TestParseTimestampToSeconds(APIBaseTest):
    @parameterized.expand(
        [
            ("zero", "00:00:00", 0),
            ("one_second", "00:00:01", 1),
            ("one_minute", "00:01:00", 60),
            ("one_hour", "01:00:00", 3600),
            ("mixed", "01:30:45", 5445),
            ("two_minutes", "00:02:00", 120),
            ("single_digit_hour", "1:00:00", 3600),
        ]
    )
    def test_valid_timestamps(self, _name: str, timestamp: str, expected: int):
        self.assertEqual(parse_timestamp_to_seconds(timestamp), expected)

    @parameterized.expand(
        [
            ("invalid_format_no_colons", "123456"),
            ("invalid_format_two_parts", "00:00"),
            ("invalid_minutes_60", "00:60:00"),
            ("invalid_seconds_60", "00:00:60"),
            ("invalid_negative", "-1:00:00"),
            ("invalid_letters", "ab:cd:ef"),
        ]
    )
    def test_invalid_timestamps(self, _name: str, timestamp: str):
        with self.assertRaises(ValueError):
            parse_timestamp_to_seconds(timestamp)


class TestVisuallyAnalyzeSessionSegmentMCPToolAPI(APIBaseTest):
    TOOL_NAME = "visually_analyze_segment_of_session_recording"
    ENDPOINT_TEMPLATE = "/api/environments/{team_id}/mcp_tools/{tool_name}/"

    def _url(self):
        return self.ENDPOINT_TEMPLATE.format(team_id=self.team.id, tool_name=self.TOOL_NAME)

    def test_tool_is_registered(self):
        from ee.hogai.mcp_tool import mcp_tool_registry

        tool = mcp_tool_registry.get(self.TOOL_NAME, self.team, self.user)
        self.assertIsNotNone(tool)

    def test_missing_args_returns_400(self):
        response = self.client.post(self._url(), {"args": {}}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_start_timestamp_format(self):
        response = self.client.post(
            self._url(),
            {
                "args": {
                    "session_id": "test-session",
                    "start_timestamp": "invalid",
                    "end_timestamp": "00:01:00",
                    "angle": "test",
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("Invalid timestamp", data["content"])

    def test_end_before_start_returns_error(self):
        response = self.client.post(
            self._url(),
            {
                "args": {
                    "session_id": "test-session",
                    "start_timestamp": "00:02:00",
                    "end_timestamp": "00:01:00",
                    "angle": "test",
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("must be after", data["content"])

    def test_segment_too_long_returns_error(self):
        response = self.client.post(
            self._url(),
            {
                "args": {
                    "session_id": "test-session",
                    "start_timestamp": "00:00:00",
                    "end_timestamp": "00:05:00",
                    "angle": "test",
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn(str(MAX_SEGMENT_DURATION_S), data["content"])

    def test_segment_exactly_2_minutes_is_allowed(self):
        with patch(
            "ee.hogai.tools.visually_analyze_session_segment.mcp_tool.VisuallyAnalyzeSessionSegmentMCPTool.execute",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = "Analysis result"
            response = self.client.post(
                self._url(),
                {
                    "args": {
                        "session_id": "test-session",
                        "start_timestamp": "00:00:00",
                        "end_timestamp": "00:02:00",
                        "angle": "look for UI issues",
                    }
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            data = response.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["content"], "Analysis result")

    @patch(
        "ee.hogai.tools.visually_analyze_session_segment.mcp_tool.VisuallyAnalyzeSessionSegmentMCPTool.execute",
        new_callable=AsyncMock,
    )
    def test_successful_analysis(self, mock_execute):
        mock_execute.return_value = "User clicked the button and navigated to checkout."
        response = self.client.post(
            self._url(),
            {
                "args": {
                    "session_id": "test-session-123",
                    "start_timestamp": "00:01:00",
                    "end_timestamp": "00:02:30",
                    "angle": "focus on the checkout flow",
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("checkout", data["content"])
        mock_execute.assert_called_once()

    @patch("ee.hogai.tools.replay.visually_analyze_session_segment._session_belongs_to_team", return_value=True)
    @patch("ee.hogai.tools.replay.visually_analyze_session_segment.GeminiVideoUnderstandingProvider")
    @patch(
        "ee.hogai.tools.replay.visually_analyze_session_segment.async_connect",
        new_callable=AsyncMock,
    )
    def test_full_flow_with_mocked_temporal_and_gemini(
        self, mock_connect, mock_gemini_cls, mock_session_belongs_to_team
    ):
        mock_client = AsyncMock()
        mock_connect.return_value = mock_client

        mock_provider = AsyncMock()
        mock_provider.understand_video = AsyncMock(return_value="The user scrolled through the page.")
        mock_gemini_cls.return_value = mock_provider

        from posthog.models.exported_asset import ExportedAsset

        with patch.object(
            ExportedAsset.objects,
            "aget",
            new_callable=AsyncMock,
            return_value=ExportedAsset(content=b"fake-video-data"),
        ):
            response = self.client.post(
                self._url(),
                {
                    "args": {
                        "session_id": "session-abc",
                        "start_timestamp": "00:00:30",
                        "end_timestamp": "00:01:00",
                        "angle": "look for scrolling behavior",
                    }
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("scrolled", data["content"])

        mock_client.execute_workflow.assert_called_once()
        mock_provider.understand_video.assert_called_once()
        mock_session_belongs_to_team.assert_called_once()

    @patch(
        "ee.hogai.tools.replay.visually_analyze_session_segment.ExportedAsset.objects.acreate", new_callable=AsyncMock
    )
    @patch("ee.hogai.tools.replay.visually_analyze_session_segment._session_belongs_to_team", return_value=False)
    def test_unknown_or_cross_team_session_is_rejected(self, mock_session_belongs_to_team, mock_create_asset):
        response = self.client.post(
            self._url(),
            {
                "args": {
                    "session_id": "session-from-another-team",
                    "start_timestamp": "00:00:30",
                    "end_timestamp": "00:01:00",
                    "angle": "look for scrolling behavior",
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("No session recording was found", data["content"])
        mock_session_belongs_to_team.assert_called_once()
        mock_create_asset.assert_not_called()
