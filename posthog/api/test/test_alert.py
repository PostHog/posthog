from unittest import mock

from rest_framework import status

from posthog.test.base import APIBaseTest, QueryMatchingTest
from posthog.models.insight import Insight
from posthog.models.filters.filter import Filter


class TestAlert(APIBaseTest, QueryMatchingTest):
    insight: Insight = None  # type: ignore

    insight_filter_dict = {
        "events": [{"id": "$pageview"}],
        "properties": [{"key": "$browser", "value": "Mac OS X"}],
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.insight = Insight.objects.create(
            filters=Filter(data=cls.insight_filter_dict).to_dict(),
            team=cls.team,
            created_by=cls.user,
        )

    def _create_alert(self, **kwargs):
        payload = {
            "insight": self.insight.id,
            "target_value": "test@posthog.com",
            "name": "alert name",
            "anomaly_condition": {},
        }

        payload.update(kwargs)
        return self.client.post(f"/api/projects/{self.team.id}/alerts", payload)

    def test_creates_alert_successfully(self) -> None:
        response = self._create_alert()

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == {
            "id": mock.ANY,
            "insight": self.insight.id,
            "target_value": "test@posthog.com",
            "name": "alert name",
            "anomaly_condition": {},
        }
