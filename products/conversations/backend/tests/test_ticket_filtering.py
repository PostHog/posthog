from posthog.test.base import APIBaseTest

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Priority
from products.conversations.backend.ticket_filtering import apply_ticket_filters, rule_filter_params


class TestTicketFiltering(APIBaseTest):
    def _make_ticket(self, number: int, **kwargs) -> Ticket:
        defaults = {
            "team": self.team,
            "ticket_number": number,
            "widget_session_id": f"s-{number}",
            "distinct_id": f"p-{number}",
        }
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def test_apply_ticket_filters_matches_list_endpoint(self):
        # A rule stores the same query-param strings the list view uses; both must count
        # the same tickets so "create alert rule from filters" is faithful.
        self._make_ticket(1, channel_source=Channel.EMAIL, priority=Priority.HIGH)
        self._make_ticket(2, channel_source=Channel.EMAIL, priority=Priority.LOW)
        self._make_ticket(3, channel_source=Channel.WIDGET, priority=Priority.HIGH)

        params = {"channel_source": "email", "priority": "high"}

        # The list endpoint applies the same params via apply_ticket_filters.
        list_response = self.client.get(f"/api/projects/{self.team.pk}/conversations/tickets/", params)
        assert list_response.status_code == 200
        list_ids = {row["id"] for row in list_response.json()["results"]}

        # Rule evaluation path.
        helper_qs = apply_ticket_filters(Ticket.objects.filter(team_id=self.team.id), params, self.team)
        helper_ids = {str(t.id) for t in helper_qs}

        assert helper_ids == list_ids
        assert len(helper_ids) == 1  # only the email + high-priority ticket

    def test_rule_filter_params_keeps_only_allowed_keys(self):
        # Time/order params would fight the rule's window; search is disallowed in
        # rules (unindexed comment scan on a recurring background job).
        cleaned = rule_filter_params(
            {
                "channel_source": "email",
                "date_from": "-7d",
                "order_by": "-created_at",
                "search": "csv export",
            }
        )
        assert cleaned == {"channel_source": "email"}
