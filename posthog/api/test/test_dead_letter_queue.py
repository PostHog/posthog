import datetime as dt

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status


class TestDeadLetterQueueAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    @parameterized.expand(
        [
            ("nonzero_size", "dlq_size", 37, 37),
            ("zero_size", "dlq_size", 0, 0),
            (
                "last_error_timestamp",
                "dlq_last_error_timestamp",
                dt.datetime(2024, 5, 1, 12, 30, tzinfo=dt.UTC),
                "2024-05-01T12:30:00Z",
            ),
        ]
    )
    def test_retrieve_scalar_metric_returns_value(self, _name, key, query_result, expected_value) -> None:
        with patch("posthog.api.dead_letter_queue.sync_execute", return_value=[(query_result,)]):
            response = self.client.get(f"/api/dead_letter_queue/{key}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["value"] == expected_value
        assert response.json()["subrows"] is None
