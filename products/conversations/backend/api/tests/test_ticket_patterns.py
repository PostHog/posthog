from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from posthog.models import Team

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status
from products.conversations.backend.temporal.ticket_patterns.recent import record_spike

DETECTED_AT = "2026-09-17T12:00:00Z"
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
        record_spike(
            (team or self.team).id,
            {
                "topic": TOPIC,
                "summary": "Several customers cannot complete a payment.",
                "ticket_ids": [str(t.id) for t in tickets],
                "ticket_count": len(tickets),
                "requester_count": len(tickets),
                "detected_at": DETECTED_AT,
            },
        )
        return f"{TOPIC}:{DETECTED_AT}"

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

    def test_a_spike_carries_only_the_tickets_the_user_can_open(self):
        # The point of scoping this endpoint as ticket data: a spike must not hand someone the ids
        # and blast radius of tickets they cannot open.
        self._record(self.tickets)
        readable = self.tickets[:1]

        with (
            patch(
                "products.access_control.backend.facade.user_access_control.UserAccessControl.has_resource_access",
                return_value=False,
            ),
            patch(
                "products.access_control.backend.facade.user_access_control.UserAccessControl.filter_queryset_by_access_level",
                side_effect=lambda qs, *a, **kw: qs.filter(id__in=[t.id for t in readable]),
            ),
        ):
            listed = self._list()

        assert len(listed) == 1
        assert listed[0]["ticket_ids"] == [str(readable[0].id)]
        assert listed[0]["ticket_count"] == 1
        assert listed[0]["requester_count"] == 1

    def test_a_spike_whose_tickets_are_all_hidden_is_not_listed(self):
        self._record(self.tickets)

        with (
            patch(
                "products.access_control.backend.facade.user_access_control.UserAccessControl.has_resource_access",
                return_value=False,
            ),
            patch(
                "products.access_control.backend.facade.user_access_control.UserAccessControl.filter_queryset_by_access_level",
                side_effect=lambda qs, *a, **kw: qs.none(),
            ),
        ):
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

    def test_a_user_who_cannot_see_the_spike_cannot_dismiss_it(self):
        key = self._record(self.tickets)

        with (
            patch(
                "products.access_control.backend.facade.user_access_control.UserAccessControl.has_resource_access",
                return_value=False,
            ),
            patch(
                "products.access_control.backend.facade.user_access_control.UserAccessControl.filter_queryset_by_access_level",
                side_effect=lambda qs, *a, **kw: qs.none(),
            ),
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/conversations/ticket_patterns/dismiss/", {"key": key}
            )

        assert response.status_code == 404, response.content

    def test_turning_detection_off_stops_serving_spikes(self):
        self._record(self.tickets)
        self.team.conversations_settings = {"ticket_patterns_enabled": False}
        self.team.save()

        assert self._list() == []

    def test_pulling_the_rollout_flag_stops_serving_spikes(self):
        self._record(self.tickets)

        with patch(f"{ELIGIBILITY_MODULE}.is_master_flag_enabled", return_value=False):
            assert self._list() == []
