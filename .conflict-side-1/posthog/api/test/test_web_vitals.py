from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from rest_framework import status

from posthog.models.utils import uuid7


class TestWebVitalsAPI(ClickhouseTestMixin, APIBaseTest):
    def assert_values(self, results, expected_values):
        # Verify that all web vitals metrics are present in the response
        metrics = [result["action"]["custom_name"] for result in results]
        self.assertCountEqual(metrics, ["INP", "LCP", "CLS", "FCP"])

        # Verify the p90 values of the metrics
        for result in results:
            custom_name = result["action"]["custom_name"]

            if custom_name == "INP":
                self.assertEqual(result["data"][-1], expected_values["INP"])
            elif custom_name == "LCP":
                self.assertEqual(result["data"][-1], expected_values["LCP"])
            elif custom_name == "CLS":
                self.assertEqual(result["data"][-1], expected_values["CLS"])
            elif custom_name == "FCP":
                self.assertEqual(result["data"][-1], expected_values["FCP"])

    def test_web_vitals_missing_pathname(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/web_vitals/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "attr": "pathname",
                "code": "invalid_input",
                "detail": "This field is required.",
            },
        )

    def test_web_vitals_with_data(self):
        # Freeze time at query time
        timestamp = f"2024-01-07T12:00:00.000Z"
        with freeze_time(timestamp):
            session_id = str(uuid7("2024-01-07"))

            # Create some events for each of the metrics
            for count in range(8):
                # Create INP events, P90 for 8 events is 365
                _create_event(
                    team=self.team,
                    event="$web_vitals",
                    distinct_id="test_user",
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": "/test-path",
                        "$web_vitals_INP_value": 50 + (count * 50),
                    },
                )

                # Create LCP events, P90 for 8 events is 4150
                _create_event(
                    team=self.team,
                    event="$web_vitals",
                    distinct_id="test_user",
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": "/test-path",
                        "$web_vitals_LCP_value": 1000 + (count * 500),
                    },
                )

                # Create CLS events, P90 for 8 events is 0.73
                _create_event(
                    team=self.team,
                    event="$web_vitals",
                    distinct_id="test_user",
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": "/test-path",
                        "$web_vitals_CLS_value": 0.1 + (count * 0.1),
                    },
                )

                # Create FCP events, P90 for 8 events is 2390
                _create_event(
                    team=self.team,
                    event="$web_vitals",
                    distinct_id="test_user",
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": "/test-path",
                        "$web_vitals_FCP_value": 500 + (count * 300),
                    },
                )

            # Create events for a different path that should not affect results
            _create_event(
                team=self.team,
                event="$web_vitals",
                distinct_id="test_user",
                timestamp=timestamp,
                properties={
                    "$session_id": session_id,
                    "$pathname": "/other-path",
                    "$web_vitals_INP_value": 9999,
                },
            )
            _create_event(
                team=self.team,
                event="$web_vitals",
                distinct_id="test_user",
                timestamp=timestamp,
                properties={
                    "$session_id": session_id,
                    "$pathname": "/other-path",
                    "$web_vitals_LCP_value": 9999,
                },
            )
            _create_event(
                team=self.team,
                event="$web_vitals",
                distinct_id="test_user",
                timestamp=timestamp,
                properties={
                    "$session_id": session_id,
                    "$pathname": "/other-path",
                    "$web_vitals_CLS_value": 9.9,
                },
            )

            _create_event(
                team=self.team,
                event="$web_vitals",
                distinct_id="test_user",
                timestamp=timestamp,
                properties={
                    "$session_id": session_id,
                    "$pathname": "/other-path",
                    "$web_vitals_FCP_value": 9999,
                },
            )

            # Flush the events to ClickHouse
            flush_persons_and_events()

            response = self.client.get(f"/api/environments/{self.team.pk}/web_vitals/?pathname=/test-path")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            data = response.json()
            self.assertIn("results", data)
            self.assertTrue(len(data["results"]) > 0)

            # P90 for the values computed above
            expected_values = {"INP": 365, "LCP": 4150, "CLS": 0.73, "FCP": 2390}
            self.assert_values(data["results"], expected_values)

    def test_web_vitals_no_data(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/web_vitals/?pathname=/test-path")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("results", data)
        self.assertTrue(len(data["results"]) > 0)

        # Empty, return all zeros
        expected_values = {"INP": 0, "LCP": 0, "CLS": 0, "FCP": 0}
        self.assert_values(data["results"], expected_values)
