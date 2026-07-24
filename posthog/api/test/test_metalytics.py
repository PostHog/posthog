from posthog.test.base import APIBaseTest
from unittest.mock import patch


class TestMetalytics(APIBaseTest):
    def test_records_view(self) -> None:
        with patch("posthog.api.metalytics.get_producer") as mock_get_producer:
            response = self.client.post(
                f"/api/projects/{self.team.id}/metalytics/",
                {"metric_name": "viewed", "instance_id": "Insight:123"},
            )

        self.assertEqual(response.status_code, 200, response.content)
        mock_get_producer.return_value.produce.assert_called_once()

    def test_kafka_failure_does_not_500(self) -> None:
        # Best-effort telemetry: a Kafka hiccup must return success, not surface as a 5xx.
        with patch("posthog.api.metalytics.get_producer") as mock_get_producer:
            mock_get_producer.return_value.produce.side_effect = Exception("kafka down")
            response = self.client.post(
                f"/api/projects/{self.team.id}/metalytics/",
                {"metric_name": "viewed", "instance_id": "Insight:123"},
            )

        self.assertEqual(response.status_code, 200, response.content)

    def test_invalid_metric_name_is_rejected(self) -> None:
        with patch("posthog.api.metalytics.get_producer"):
            response = self.client.post(
                f"/api/projects/{self.team.id}/metalytics/",
                {"metric_name": "not_a_metric", "instance_id": "Insight:123"},
            )

        self.assertEqual(response.status_code, 400, response.content)
