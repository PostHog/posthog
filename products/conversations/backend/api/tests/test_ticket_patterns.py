from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from posthog.models import Team

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status
from products.conversations.backend.temporal.ticket_patterns.recent import record_spike

TOPIC = "checkout failing"
ELIGIBILITY_MODULE = "products.conversations.backend.api.ticket_patterns"


class TestTicketPatternsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.team.conversations_settings = {"ticket_patterns_enabled": True}
        self.team.save()
        self.tickets = [self._make_ticket(number) for number in (1, 2, 3)]
        self.flag_patch = patch(f"{ELIGIBILITY_MODULE}.is_master_flag_enabled", return_value=True)
        self.flag_patch.start()
        self.addCleanup(self.flag_patch.stop)

    def _make_ticket(self, number: int, team: Team | None = None) -> Ticket:
        return Ticket.objects.create(
            team=team or self.team,
            ticket_number=number,
            channel_source="email",
            widget_session_id=f"session-{number}",
            distinct_id=f"customer-{number}",
            status=Status.OPEN,
            email_subject=f"Cannot pay {number}",
        )

    def _record(self, tickets: list[Ticket], team: Team | None = None) -> str:
        # Relative, not a literal: the endpoint only serves spikes from the last day, so a fixed
        # timestamp would stop meaning "recent" as soon as real time moved past it.
        detected_at = timezone.now().isoformat()
        record_spike(
            (team or self.team).id,
            {
                "topic": TOPIC,
                "summary": "Several customers cannot complete a payment.",
                "ticket_ids": [str(t.id) for t in tickets],
                "ticket_count": len(tickets),
                "requester_count": len(tickets),
                "detected_at": detected_at,
            },
        )
        return f"{TOPIC}:{detected_at}"

    def _only_these_tickets_readable(self, tickets: list[Ticket]):
        ids = [t.id for t in tickets]
        return patch.multiple(
            "products.access_control.backend.facade.user_access_control.UserAccessControl",
            has_resource_access=lambda *a, **kw: False,
            filter_queryset_by_access_level=lambda self, qs, *a, **kw: qs.filter(id__in=ids),
        )

    def _list(self) -> list[dict]:
        response = self.client.get(f"/api/projects/{self.team.id}/conversations/ticket_patterns/")
        assert response.status_code == 200, response.content
        return response.json()

    def test_lists_this_projects_spikes(self):
        self._record(self.tickets)

        listed = self._list()

        assert [s["topic"] for s in listed] == [TOPIC]
        assert listed[0]["ticket_count"] == 3

    def test_another_projects_spikes_are_not_returned(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self._record([self._make_ticket(9, team=other_team)], team=other_team)

        assert self._list() == []

    def test_a_spike_is_hidden_unless_every_one_of_its_tickets_is_readable(self):
        # The topic and summary are written from the whole cluster, so narrowing the id list would
        # still hand over text derived from tickets the user cannot open.
        self._record(self.tickets)

        with self._only_these_tickets_readable(self.tickets[:1]):
            assert self._list() == []

    def test_a_spike_is_listed_whole_when_every_ticket_is_readable(self):
        self._record(self.tickets)

        with self._only_these_tickets_readable(self.tickets):
            listed = self._list()

        assert len(listed) == 1
        assert listed[0]["ticket_count"] == 3

    def test_a_spike_whose_tickets_are_all_hidden_is_not_listed(self):
        self._record(self.tickets)

        with self._only_these_tickets_readable([]):
            assert self._list() == []

    def test_dismissal_hides_the_spike_for_everyone(self):
        self.user.first_name = "Robin"
        self.user.save()
        key = self._record(self.tickets)

        response = self.client.post(
            f"/api/projects/{self.team.id}/conversations/ticket_patterns/dismiss/", {"key": key}
        )
        assert response.status_code == 204, response.content

        # A second person reading the list sees it already dismissed, and by whom.
        listed = self._list()
        assert listed[0]["dismissed_by"] == "Robin"
        assert listed[0]["dismissed_at"] is not None

    def test_dismissing_an_unknown_spike_is_a_404(self):
        self._record(self.tickets)

        response = self.client.post(
            f"/api/projects/{self.team.id}/conversations/ticket_patterns/dismiss/", {"key": "nope:nope"}
        )

        assert response.status_code == 404, response.content

    def test_partial_ticket_access_cannot_dismiss_for_the_whole_project(self):
        # Dismissing hides the spike for everyone, so someone who can read only part of it must
        # not be able to clear the warning for the teammates who can read all of it.
        key = self._record(self.tickets)

        with self._only_these_tickets_readable(self.tickets[:1]):
            response = self.client.post(
                f"/api/projects/{self.team.id}/conversations/ticket_patterns/dismiss/", {"key": key}
            )

        assert response.status_code == 404, response.content

    def test_a_cached_id_the_model_cannot_parse_drops_the_banner_not_the_page(self):
        # The banner loads on the inbox scene, so a cache blob the Ticket model chokes on must
        # cost the banner rather than the ticket list behind it.
        record_spike(
            self.team.id,
            {
                "topic": TOPIC,
                "summary": "",
                "ticket_ids": ["not-a-uuid"],
                "ticket_count": 1,
                "requester_count": 1,
                "detected_at": timezone.now().isoformat(),
            },
        )

        assert self._list() == []

    def test_turning_detection_off_stops_serving_spikes(self):
        self._record(self.tickets)
        self.team.conversations_settings = {"ticket_patterns_enabled": False}
        self.team.save()

        assert self._list() == []

    def test_pulling_the_rollout_flag_stops_serving_spikes(self):
        self._record(self.tickets)

        with patch(f"{ELIGIBILITY_MODULE}.is_master_flag_enabled", return_value=False):
            assert self._list() == []
