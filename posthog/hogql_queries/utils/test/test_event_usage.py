from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.hogql_queries.utils.event_usage import MAX_PROPERTIES_LOGGED_PER_QUERY, log_event_usage_from_query_metadata


class TestLogEventUsageFromQueryMetadata(SimpleTestCase):
    def _producer(self, mock_get_producer: MagicMock) -> MagicMock:
        producer = MagicMock()
        mock_get_producer.return_value = producer
        return producer

    @patch("posthog.hogql_queries.utils.event_usage.get_producer")
    def test_logs_event_and_property_payloads(self, mock_get_producer):
        producer = self._producer(mock_get_producer)

        log_event_usage_from_query_metadata(
            {
                "events": ["$pageview"],
                "properties": [
                    {"type": "event", "name": "$browser"},
                    {"type": "person", "name": "email"},
                ],
            },
            team_id=42,
            user_id=7,
        )

        payloads = [call.kwargs["data"] for call in producer.produce.call_args_list]
        self.assertEqual(len(payloads), 3)

        property_payloads = [payload for payload in payloads if payload["app_source"] == "property_usage"]
        self.assertEqual(
            {payload["instance_id"] for payload in property_payloads},
            {"property:event:$browser", "property:person:email"},
        )
        for payload in property_payloads:
            self.assertEqual(payload["team_id"], 42)
            self.assertEqual(payload["metric_name"], "viewed")
            self.assertEqual(payload["app_source_id"], "7")

    @patch("posthog.hogql_queries.utils.event_usage.get_producer")
    def test_caps_properties_per_query(self, mock_get_producer):
        producer = self._producer(mock_get_producer)

        log_event_usage_from_query_metadata(
            {"events": [], "properties": [{"type": "event", "name": f"prop_{i}"} for i in range(60)]},
            team_id=42,
        )

        self.assertEqual(producer.produce.call_count, MAX_PROPERTIES_LOGGED_PER_QUERY)

    @patch("posthog.hogql_queries.utils.event_usage.get_producer")
    def test_skips_malformed_property_entries(self, mock_get_producer):
        producer = self._producer(mock_get_producer)

        log_event_usage_from_query_metadata(
            {"properties": ["nope", {"type": "event"}, {"name": "x"}, {"type": "event", "name": "ok"}]},
            team_id=42,
        )

        self.assertEqual(producer.produce.call_count, 1)
        self.assertEqual(producer.produce.call_args.kwargs["data"]["instance_id"], "property:event:ok")

    @patch("posthog.hogql_queries.utils.event_usage.get_producer")
    def test_metadata_without_properties_key_logs_nothing_extra(self, mock_get_producer):
        producer = self._producer(mock_get_producer)

        log_event_usage_from_query_metadata({"events": ["$pageview"]}, team_id=42)

        self.assertEqual(producer.produce.call_count, 1)
