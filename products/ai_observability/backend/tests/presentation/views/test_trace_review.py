from decimal import Decimal

from posthog.test.base import APIBaseTest

from products.ai_observability.backend.models.review_queues import ReviewQueue, ReviewQueueItem
from products.ai_observability.backend.models.score_definitions import ScoreDefinition
from products.ai_observability.backend.models.trace_reviews import TraceReview, TraceReviewScore

from .trace_fixtures import encode_segment


class TestTraceReviewView(APIBaseTest):
    def _url(self, segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/review/"

    def _review_and_queue(self) -> ReviewQueueItem:
        review = TraceReview.objects.create(
            team=self.team, trace_id="trace-1", reviewed_by=self.user, created_by=self.user
        )
        definition = ScoreDefinition.objects.create(team=self.team, name="Tone", kind="numeric", created_by=self.user)
        version = definition.create_new_version(config={}, created_by=self.user)
        TraceReviewScore.objects.create(
            team=self.team,
            review=review,
            definition=definition,
            definition_version=version.id,
            definition_version_number=version.version,
            definition_config=version.config,
            numeric_value=Decimal("4.5"),
            created_by=self.user,
        )
        queue = ReviewQueue.objects.create(team=self.team, name="Support QA", created_by=self.user)
        return ReviewQueueItem.objects.create(team=self.team, queue=queue, trace_id="trace-1", created_by=self.user)

    def test_returns_the_status_in_camel_case(self) -> None:
        item = self._review_and_queue()

        response = self.client.get(self._url(encode_segment("trace-1")))

        assert response.status_code == 200
        body = response.json()
        assert body["review"]["reviewedBy"] == (self.user.first_name or self.user.email)
        assert body["review"]["scores"] == [{"name": "Tone", "value": "4.5", "label": "Tone: 4.5"}]
        assert body["queue"] == {"id": str(item.queue_id), "name": "Support QA", "itemId": str(item.id)}

    def test_an_unreviewed_trace_has_neither(self) -> None:
        response = self.client.get(self._url(encode_segment("trace-1")))

        assert (response.status_code, response.json()) == (200, {"review": None, "queue": None})

    def test_rejects_an_unencoded_trace_id(self) -> None:
        assert self.client.get(self._url("trace-1")).status_code == 400

    def test_a_personal_api_key_with_the_trace_scope_can_read(self) -> None:
        self.client.logout()
        key = self.create_personal_api_key_with_scopes(["llm_analytics:read"])

        response = self.client.get(self._url(encode_segment("trace-1")), headers={"authorization": f"Bearer {key}"})

        assert response.status_code == 200, response.content
