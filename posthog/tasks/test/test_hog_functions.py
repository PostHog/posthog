from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.schema import HogQLQueryResponse

from posthog.models.hog_functions.hog_function import HogFunction
from posthog.tasks.hog_functions import batch_retry_hog_function


class TestHogFunctionsTasks(BaseTest):
    def setUp(self):
        super().setUp()
        self.hog_function = HogFunction.objects.create(
            team=self.team,
            name="Test HF",
            type="destination",
            hog="print(event)",
            inputs={"url": "http://example.com"},
            filters={"events": [{"id": "$pageview"}]},
            enabled=True,
        )

    @patch("posthog.tasks.hog_functions.create_hog_invocation_test")
    @patch("posthog.tasks.hog_functions.execute_hogql_query")
    def test_batch_retry_hog_function(self, mock_execute_hogql, mock_create_test):
        # 1. Mock response for log entries query (SELECT message, instance_id)
        # Returns [message, instance_id]
        log_response = HogQLQueryResponse(
            results=[
                [f"Error executing function on Event: uuid-1", "inst-1"],
                [f"Some other message Event: uuid-2", "inst-2"],
            ]
        )

        # 2. Mock response for events query
        # Returns [uuid, distinct_id, event, timestamp, properties, elements_chain, person_id, person_props, person_created_at]
        events_response = HogQLQueryResponse(
            results=[
                [
                    "uuid-1",  # uuid
                    "u1",  # distinct_id
                    "$pageview",  # event
                    "2024-01-01 00:00:00",  # timestamp
                    '{"prop": "val"}',  # properties
                    "[]",  # elements_chain
                    "p1",  # person.id
                    '{"pprop": "pval"}',  # person.properties
                    "2024-01-01",  # person.created_at
                ],
                [
                    "uuid-2",
                    "u2",
                    "$autocapture",
                    "2024-01-01 00:00:00",
                    '{"prop": "val2"}',
                    "[]",
                    "p2",
                    "{}",
                    "2024-01-01",
                ],
            ]
        )

        mock_execute_hogql.side_effect = [log_response, events_response]

        # Execute
        batch_retry_hog_function(
            team_id=self.team.id,
            hog_function_id=str(self.hog_function.id),
            date_from="2024-01-01 00:00:00",
            date_to="2024-01-02 00:00:00",
            status="error",
        )

        # Verify

        # Verify execute_hogql_query calls

        found_logs_call = False
        found_events_call = False

        for call in mock_execute_hogql.call_args_list:
            values = call.kwargs.get("values", {})
            if "hog_function_id" in values:
                found_logs_call = True
                self.assertEqual(values["hog_function_id"], str(self.hog_function.id))
                self.assertEqual(values["status"], "error")
            elif "batch_ids" in values:
                found_events_call = True
                self.assertIn("uuid-1", values["batch_ids"])
                self.assertIn("uuid-2", values["batch_ids"])

        self.assertTrue(found_logs_call, "Did not find logs query call")
        self.assertTrue(found_events_call, "Did not find events query call")

        # 3. Verify create_hog_invocation_test calls
        self.assertEqual(mock_create_test.call_count, 2)

        # Verify payload for first event (order depends on set iteration but we can check existence)
        calls = mock_create_test.call_args_list
        uuids_called = [c.kwargs["payload"]["clickhouse_event"]["uuid"] for c in calls]
        self.assertIn("uuid-1", uuids_called)
        self.assertIn("uuid-2", uuids_called)

        # detailed check for one
        call_1 = next(c for c in calls if c.kwargs["payload"]["clickhouse_event"]["uuid"] == "uuid-1")
        self.assertEqual(call_1.kwargs["hog_function_id"], str(self.hog_function.id))
        payload_1 = call_1.kwargs["payload"]
        self.assertEqual(payload_1["configuration"]["id"], self.hog_function.id)
        # self.assertEqual(payload_1["configuration"]["inputs"], {"url": "http://example.com"})
