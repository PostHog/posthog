from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status


class TestDeadLetterQueueAPI(APIBaseTest):
    @parameterized.expand([("non_numeric", "abc"), ("negative", "-1")])
    def test_retrieve_rejects_bad_offset(self, _name: str, offset: str) -> None:
        self.user.is_staff = True
        self.user.save()

        response = self.client.get(f"/api/dead_letter_queue/dlq_events/?offset={offset}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
