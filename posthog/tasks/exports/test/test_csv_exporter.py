from unittest.mock import Mock, patch

from rest_framework_csv import renderers as csvrenderers

from posthog.models import ExportedAsset
from posthog.tasks.exports import csv_exporter
from posthog.test.base import APIBaseTest


class TestCSVExporter(APIBaseTest):
    @patch("posthog.tasks.exports.csv_exporter.requests.request")
    def test_can_render_known_responses(self, patched_request) -> None:
        """
        regression test to triangulate a test that passes locally but fails in CI
        """
        asset = ExportedAsset(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.CSV,
            export_context={"path": "/api/literally/anything"},
        )
        asset.save()

        mock_response = Mock()
        # API responses copied from https://github.com/PostHog/posthog/runs/7221634689?check_suite_focus=true
        mock_response.json.side_effect = [
            {
                "next": "http://testserver/api/projects/169/events?orderBy=%5B%22-timestamp%22%5D&properties=%5B%7B%22key%22%3A%22%24browser%22%2C%22value%22%3A%5B%22Safari%22%5D%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22event%22%7D%5D&after=2022-07-06T19%3A27%3A43.206326&limit=1&before=2022-07-06T19%3A37%3A43.095295%2B00%3A00",
                "results": [
                    {
                        "id": "e9ca132e-400f-4854-a83c-16c151b2f145",
                        "distinct_id": "2",
                        "properties": {"$browser": "Safari"},
                        "event": "event_name",
                        "timestamp": "2022-07-06T19:37:43.095295+00:00",
                        "person": None,
                        "elements": [],
                        "elements_chain": "",
                    }
                ],
            },
            {
                "next": "http://testserver/api/projects/169/events?orderBy=%5B%22-timestamp%22%5D&properties=%5B%7B%22key%22%3A%22%24browser%22%2C%22value%22%3A%5B%22Safari%22%5D%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22event%22%7D%5D&after=2022-07-06T19%3A27%3A43.206326&limit=1&before=2022-07-06T19%3A37%3A43.095279%2B00%3A00",
                "results": [
                    {
                        "id": "1624228e-a4f1-48cd-aabc-6baa3ddb22e4",
                        "distinct_id": "2",
                        "properties": {"$browser": "Safari"},
                        "event": "event_name",
                        "timestamp": "2022-07-06T19:37:43.095279+00:00",
                        "person": None,
                        "elements": [],
                        "elements_chain": "",
                    }
                ],
            },
            {
                "next": None,
                "results": [
                    {
                        "id": "66d45914-bdf5-4980-a54a-7dc699bdcce9",
                        "distinct_id": "2",
                        "properties": {"$browser": "Safari"},
                        "event": "event_name",
                        "timestamp": "2022-07-06T19:37:43.095262+00:00",
                        "person": None,
                        "elements": [],
                        "elements_chain": "",
                    }
                ],
            },
        ]
        patched_request.return_value = mock_response
        csv_exporter.export_csv(asset)

        assert (
            asset.content
            == b"distinct_id,elements_chain,event,id,person,properties.$browser,timestamp\r\n2,,event_name,e9ca132e-400f-4854-a83c-16c151b2f145,,Safari,2022-07-06T19:37:43.095295+00:00\r\n2,,event_name,1624228e-a4f1-48cd-aabc-6baa3ddb22e4,,Safari,2022-07-06T19:37:43.095279+00:00\r\n2,,event_name,66d45914-bdf5-4980-a54a-7dc699bdcce9,,Safari,2022-07-06T19:37:43.095262+00:00\r\n"
        )

    def test_can_render_known_response_using_renderer(self) -> None:
        """
        regression test to triangulate a test that passes locally but fails in CI
        """
        csv_data_gathered_in_ci = [
            {
                "id": "e9ca132e-400f-4854-a83c-16c151b2f145",
                "distinct_id": "2",
                "properties": {"$browser": "Safari"},
                "event": "event_name",
                "timestamp": "2022-07-06T19:37:43.095295+00:00",
                "person": None,
                "elements": [],
                "elements_chain": "",
            },
            {
                "id": "1624228e-a4f1-48cd-aabc-6baa3ddb22e4",
                "distinct_id": "2",
                "properties": {"$browser": "Safari"},
                "event": "event_name",
                "timestamp": "2022-07-06T19:37:43.095279+00:00",
                "person": None,
                "elements": [],
                "elements_chain": "",
            },
            {
                "id": "66d45914-bdf5-4980-a54a-7dc699bdcce9",
                "distinct_id": "2",
                "properties": {"$browser": "Safari"},
                "event": "event_name",
                "timestamp": "2022-07-06T19:37:43.095262+00:00",
                "person": None,
                "elements": [],
                "elements_chain": "",
            },
        ]

        renderer = csvrenderers.CSVRenderer()

        assert (
            renderer.render(csv_data_gathered_in_ci)
            == b"distinct_id,elements_chain,event,id,person,properties.$browser,timestamp\r\n2,,event_name,e9ca132e-400f-4854-a83c-16c151b2f145,,Safari,2022-07-06T19:37:43.095295+00:00\r\n2,,event_name,1624228e-a4f1-48cd-aabc-6baa3ddb22e4,,Safari,2022-07-06T19:37:43.095279+00:00\r\n2,,event_name,66d45914-bdf5-4980-a54a-7dc699bdcce9,,Safari,2022-07-06T19:37:43.095262+00:00\r\n"
        )
