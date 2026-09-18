from posthog.test.base import APIBaseTest

from django.core.cache import cache

from posthog.models import Team

from products.conversations.backend.temporal.ticket_patterns.recent import record_spike

SPIKE = {
    "topic": "checkout failing",
    "summary": "Several customers cannot complete a payment.",
    "ticket_ids": ["t1", "t2", "t3"],
    "ticket_count": 3,
    "requester_count": 3,
    "detected_at": "2026-09-17T12:00:00Z",
}


class TestTicketPatternsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_lists_this_projects_spikes(self):
        record_spike(self.team.id, SPIKE)

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/ticket_patterns/")

        assert response.status_code == 200, response.json()
        assert [s["topic"] for s in response.json()] == ["checkout failing"]

    def test_another_projects_spikes_are_not_returned(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        record_spike(other_team.id, SPIKE)

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/ticket_patterns/")

        assert response.status_code == 200, response.json()
        assert response.json() == []

    def test_dismissal_hides_the_spike_for_everyone(self):
        self.user.first_name = "Robin"
        self.user.save()
        record_spike(self.team.id, SPIKE)
        key = f"{SPIKE['topic']}:{SPIKE['detected_at']}"

        response = self.client.post(
            f"/api/projects/{self.team.id}/conversations/ticket_patterns/dismiss/", {"key": key}
        )
        assert response.status_code == 204, response.content

        # A second person reading the list sees it already dismissed, and by whom.
        listed = self.client.get(f"/api/projects/{self.team.id}/conversations/ticket_patterns/").json()
        assert listed[0]["dismissed_by"] == "Robin"
        assert listed[0]["dismissed_at"] is not None

    def test_dismissing_an_unknown_spike_is_a_404(self):
        record_spike(self.team.id, SPIKE)

        response = self.client.post(
            f"/api/projects/{self.team.id}/conversations/ticket_patterns/dismiss/", {"key": "nope:nope"}
        )

        assert response.status_code == 404, response.content
