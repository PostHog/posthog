import uuid
from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User
from posthog.settings import SITE_URL

from products.conversations.backend.events import (
    EVENT_SOURCE,
    _resolve_groups_from_analytics,
    capture_message_received,
    capture_message_sent,
    capture_ticket_assigned,
    capture_ticket_created,
    capture_ticket_priority_changed,
    capture_ticket_status_changed,
)
from products.conversations.backend.models import Ticket


class TestConversationEvents(BaseTest):
    def setUp(self):
        super().setUp()
        # The resolved-groups cache is keyed by (team_id, distinct_ids), both reused across tests here.
        cache.clear()
        self.widget_session_id = str(uuid.uuid4())
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="customer-123",
            channel_source="widget",
            status="new",
            priority="high",
            anonymous_traits={"name": "Test Customer", "email": "test@example.com"},
        )

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_ticket_created_uses_team_token(self, mock_capture):
        capture_ticket_created(self.ticket)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_ticket_created"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.ticket.distinct_id
        assert call_kwargs["properties"]["ticket_id"] == str(self.ticket.id)
        assert call_kwargs["properties"]["customer_name"] == "Test Customer"
        assert call_kwargs["properties"]["customer_email"] == "test@example.com"

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_ticket_status_changed_uses_team_token(self, mock_capture):
        capture_ticket_status_changed(self.ticket, "new", "pending", actor=self.user, actor_type="user")

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_ticket_status_changed"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.user.distinct_id
        assert call_kwargs["properties"]["old_status"] == "new"
        assert call_kwargs["properties"]["new_status"] == "pending"
        assert call_kwargs["properties"]["actor_type"] == "user"
        assert call_kwargs["properties"]["actor_id"] == self.user.id
        assert call_kwargs["properties"]["actor_email"] == self.user.email
        # Customer identity travels alongside the actor so workflows can email the customer,
        # not the team member the event's distinct_id is attributed to.
        assert call_kwargs["properties"]["customer_name"] == "Test Customer"
        assert call_kwargs["properties"]["customer_email"] == "test@example.com"
        assert call_kwargs["properties"]["customer_distinct_id"] == self.ticket.distinct_id

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_ticket_priority_changed_uses_team_token(self, mock_capture):
        capture_ticket_priority_changed(self.ticket, None, "high", actor=self.user, actor_type="user")

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_ticket_priority_changed"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.user.distinct_id
        assert call_kwargs["properties"]["old_priority"] is None
        assert call_kwargs["properties"]["new_priority"] == "high"
        assert call_kwargs["properties"]["actor_type"] == "user"
        assert call_kwargs["properties"]["actor_id"] == self.user.id
        assert call_kwargs["properties"]["actor_email"] == self.user.email
        assert call_kwargs["properties"]["customer_email"] == "test@example.com"
        assert call_kwargs["properties"]["customer_distinct_id"] == self.ticket.distinct_id

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_ticket_assigned_uses_team_token(self, mock_capture):
        capture_ticket_assigned(self.ticket, "user", "123", actor=self.user, actor_type="user")

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_ticket_assigned"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.user.distinct_id
        assert call_kwargs["properties"]["assignee_type"] == "user"
        assert call_kwargs["properties"]["assignee_id"] == "123"
        assert call_kwargs["properties"]["actor_type"] == "user"
        assert call_kwargs["properties"]["actor_id"] == self.user.id
        assert call_kwargs["properties"]["actor_email"] == self.user.email
        assert call_kwargs["properties"]["customer_email"] == "test@example.com"
        assert call_kwargs["properties"]["customer_distinct_id"] == self.ticket.distinct_id

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_message_sent_uses_team_token(self, mock_capture):
        capture_message_sent(self.ticket, "msg-123", "Hello customer", author=self.user)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_message_sent"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.user.distinct_id
        assert call_kwargs["properties"]["message_id"] == "msg-123"
        assert call_kwargs["properties"]["message_content"] == "Hello customer"
        assert call_kwargs["properties"]["author_type"] == "team"
        assert call_kwargs["properties"]["actor_type"] == "user"
        assert call_kwargs["properties"]["actor_id"] == self.user.id
        assert call_kwargs["properties"]["actor_email"] == self.user.email
        assert call_kwargs["properties"]["customer_name"] == "Test Customer"
        assert call_kwargs["properties"]["customer_email"] == "test@example.com"
        assert call_kwargs["properties"]["customer_distinct_id"] == self.ticket.distinct_id

    @parameterized.expand(
        [
            (
                "no_sla",
                None,
                {"sla_due_at": None, "sla_active": False, "sla_breached": False, "sla_delta_seconds": None},
            ),
            (
                "on_track",
                "2026-01-01T13:00:00+00:00",
                {
                    "sla_due_at": "2026-01-01T13:00:00+00:00",
                    "sla_active": True,
                    "sla_breached": False,
                    "sla_delta_seconds": -3600,
                },
            ),
            (
                "breached",
                "2026-01-01T11:00:00+00:00",
                {
                    "sla_due_at": "2026-01-01T11:00:00+00:00",
                    "sla_active": True,
                    "sla_breached": True,
                    "sla_delta_seconds": 3600,
                },
            ),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_message_sent_stamps_sla_state(self, _name, sla_due_at, expected, mock_capture):
        self.ticket.sla_due_at = datetime.fromisoformat(sla_due_at) if sla_due_at else None

        with freeze_time("2026-01-01T12:00:00Z"):
            capture_message_sent(self.ticket, "msg-123", "Hello customer", author=self.user)

        properties = mock_capture.call_args.kwargs["properties"]
        assert {key: properties[key] for key in expected} == expected

    @parameterized.expand(
        [
            ("capture_ticket_created", capture_ticket_created, []),
            ("capture_message_received", capture_message_received, ["msg-id", "content"]),
            ("capture_message_sent", capture_message_sent, ["msg-id", "content"]),
            ("capture_ticket_status_changed", capture_ticket_status_changed, ["new", "pending"]),
            ("capture_ticket_priority_changed", capture_ticket_priority_changed, [None, "high"]),
            ("capture_ticket_assigned", capture_ticket_assigned, ["user", "123"]),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    def test_customer_email_falls_back_to_email_from(self, _name, capture_fn, extra_args, mock_capture):
        self.ticket.anonymous_traits = {}
        self.ticket.email_from = "customer@example.com"

        if capture_fn is capture_message_sent:
            capture_message_sent(self.ticket, "msg-id", "content", author=self.user)
        else:
            capture_fn(self.ticket, *extra_args)

        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["properties"]["customer_email"] == "customer@example.com"

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_message_received_uses_team_token(self, mock_capture):
        capture_message_received(self.ticket, "msg-456", "Hello support")

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["event_name"] == "$conversation_message_received"
        assert call_kwargs["event_source"] == EVENT_SOURCE
        assert call_kwargs["distinct_id"] == self.ticket.distinct_id
        assert call_kwargs["properties"]["message_id"] == "msg-456"
        assert call_kwargs["properties"]["message_content"] == "Hello support"
        assert call_kwargs["properties"]["author_type"] == "customer"
        assert call_kwargs["properties"]["customer_name"] == "Test Customer"
        assert call_kwargs["properties"]["customer_email"] == "test@example.com"

    @parameterized.expand(
        [
            ("capture_ticket_created", capture_ticket_created, "$conversation_ticket_created", []),
            (
                "capture_ticket_status_changed",
                capture_ticket_status_changed,
                "$conversation_ticket_status_changed",
                ["old", "new"],
            ),
            (
                "capture_ticket_priority_changed",
                capture_ticket_priority_changed,
                "$conversation_ticket_priority_changed",
                [None, "high"],
            ),
            ("capture_ticket_assigned", capture_ticket_assigned, "$conversation_ticket_assigned", ["user", "123"]),
            ("capture_message_sent", capture_message_sent, "$conversation_message_sent", ["msg-id", "content"]),
            (
                "capture_message_received",
                capture_message_received,
                "$conversation_message_received",
                ["msg-id", "content"],
            ),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    def test_all_events_include_base_properties(self, _name, capture_fn, expected_event, extra_args, mock_capture):
        capture_fn(self.ticket, *extra_args)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["event_name"] == expected_event
        props = call_kwargs["properties"]
        assert props["ticket_id"] == str(self.ticket.id)
        assert props["ticket_number"] == self.ticket.ticket_number
        assert props["channel_source"] == self.ticket.channel_source
        assert props["status"] == self.ticket.status
        assert props["priority"] == self.ticket.priority

    @patch("products.conversations.backend.events.capture_internal")
    def test_message_content_truncated_to_1000_chars(self, mock_capture):
        long_content = "x" * 1500
        capture_message_sent(self.ticket, "msg-id", long_content, author=self.user)

        call_kwargs = mock_capture.call_args.kwargs
        assert len(call_kwargs["properties"]["message_content"]) == 1000

    @patch("products.conversations.backend.events.capture_internal")
    def test_event_uses_ticket_team_token_not_other_team(self, mock_capture):
        """Verify events route to the ticket's team, not any other team."""
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        # Ticket belongs to self.team, not other_team
        capture_ticket_created(self.ticket)

        call_kwargs = mock_capture.call_args.kwargs
        # Must use self.team's token (ticket owner), not other_team's
        assert call_kwargs["token"] == self.team.api_token
        assert call_kwargs["token"] != other_team.api_token

    @patch("products.conversations.backend.events.capture_internal")
    def test_two_teams_events_routed_to_respective_projects(self, mock_capture):
        """Events from Team 1 ticket use Team 1 token, Team 2 ticket uses Team 2 token."""
        from posthog.models import Organization, Team

        # Create second team
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        # Create ticket for other_team
        other_ticket = Ticket.objects.create_with_number(
            team=other_team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="other-customer",
            channel_source="widget",
        )

        # Fire events for both tickets
        capture_ticket_created(self.ticket)  # Team 1
        capture_ticket_created(other_ticket)  # Team 2

        # Verify two calls were made
        assert mock_capture.call_count == 2

        # First call should use self.team's token
        first_call = mock_capture.call_args_list[0].kwargs
        assert first_call["token"] == self.team.api_token

        # Second call should use other_team's token
        second_call = mock_capture.call_args_list[1].kwargs
        assert second_call["token"] == other_team.api_token

        # Tokens must be different (proves isolation)
        assert first_call["token"] != second_call["token"]

    @parameterized.expand(
        [
            ("anonymous_person", True, False, False),
            ("no_person", False, False, False),
            ("empty_distinct_id", False, False, False),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_person_processing(
        self, _name, has_person, is_identified, expect_groups, mock_get_persons, mock_capture
    ):
        from posthog.models.person.person import Person

        is_empty_distinct_id = _name == "empty_distinct_id"
        ticket = self.ticket
        if is_empty_distinct_id:
            ticket = Ticket.objects.create_with_number(
                team=self.team,
                widget_session_id=str(uuid.uuid4()),
                distinct_id="",
                channel_source="github",
            )

        if has_person:
            mock_get_persons.return_value = [Person(team_id=self.team.id, is_identified=is_identified)]
        else:
            mock_get_persons.return_value = []

        capture_ticket_created(ticket)

        if is_empty_distinct_id:
            mock_get_persons.assert_not_called()
        else:
            mock_get_persons.assert_called_once_with(self.team.id, [ticket.distinct_id], distinct_id_limit=0)

        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is expect_groups
        assert "$groups" not in call_kwargs["properties"]

    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_groups_from_person_org(self, mock_get_persons, mock_capture):
        from posthog.models.person.person import Person

        person_org = Organization.objects.create(name="Person Org")
        person_user = User.objects.create(email="customer@example.com", distinct_id="customer-123")
        OrganizationMembership.objects.create(user=person_user, organization=person_org)

        mock_get_persons.return_value = [Person(team_id=self.team.id, is_identified=True)]

        capture_ticket_created(self.ticket)

        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is True
        groups = call_kwargs["properties"]["$groups"]
        assert groups["organization"] == str(person_org.id)
        assert groups["project"] == str(self.team.uuid)
        assert "instance" in groups

    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_message_received_groups_from_person_org(self, mock_get_persons, mock_capture):
        from posthog.models.person.person import Person

        person_org = Organization.objects.create(name="Person Org")
        person_user = User.objects.create(email="customer@example.com", distinct_id="customer-123")
        OrganizationMembership.objects.create(user=person_user, organization=person_org)

        mock_get_persons.return_value = [Person(team_id=self.team.id, is_identified=True)]

        capture_message_received(self.ticket, "msg-456", "Hello support")

        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is True
        groups = call_kwargs["properties"]["$groups"]
        assert groups["organization"] == str(person_org.id)
        assert groups["project"] == str(self.team.uuid)
        assert "instance" in groups

    @parameterized.expand(
        [
            ("anonymous_person", True, False),
            ("no_person", False, False),
            ("empty_distinct_id", False, False),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_message_received_person_processing(
        self, _name, has_person, is_identified, mock_get_persons, mock_capture
    ):
        from posthog.models.person.person import Person

        is_empty_distinct_id = _name == "empty_distinct_id"
        ticket = self.ticket
        if is_empty_distinct_id:
            ticket = Ticket.objects.create_with_number(
                team=self.team,
                widget_session_id=str(uuid.uuid4()),
                distinct_id="",
                channel_source="github",
            )

        if has_person:
            mock_get_persons.return_value = [Person(team_id=self.team.id, is_identified=is_identified)]
        else:
            mock_get_persons.return_value = []

        capture_message_received(ticket, "msg-456", "Hello support")

        if is_empty_distinct_id:
            mock_get_persons.assert_not_called()
        else:
            mock_get_persons.assert_called_once_with(self.team.id, [ticket.distinct_id], distinct_id_limit=0)

        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is False
        assert "$groups" not in call_kwargs["properties"]

    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids", side_effect=Exception("db timeout"))
    def test_capture_message_received_still_fires_on_person_lookup_failure(self, mock_get_persons, mock_capture):
        capture_message_received(self.ticket, "msg-456", "Hello support")

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is False
        assert "$groups" not in call_kwargs["properties"]

    @parameterized.expand(
        [
            ("user_not_found", False, False),
            ("user_has_no_membership", True, False),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_no_groups_when(
        self, _name, create_user, create_membership, mock_get_persons, mock_capture
    ):
        from posthog.models.person.person import Person

        if create_user:
            User.objects.create(email="lonely@example.com", distinct_id="customer-123")

        mock_get_persons.return_value = [Person(team_id=self.team.id, is_identified=True)]

        capture_ticket_created(self.ticket)

        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is False
        assert "$groups" not in call_kwargs["properties"]

    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids", side_effect=Exception("db timeout"))
    def test_capture_ticket_created_still_fires_on_person_lookup_failure(self, mock_get_persons, mock_capture):
        capture_ticket_created(self.ticket)

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is False
        assert "$groups" not in call_kwargs["properties"]

    @parameterized.expand(
        [
            # name, channel, traits_email, email_from -- exercises both the traits.email and the email_from source
            ("slack_traits_email", "slack", "biz@acme.com", None),
            ("teams_traits_email", "teams", "biz@acme.com", None),
            ("email_traits_email", "email", "biz@acme.com", None),
            ("email_from_only", "email", None, "biz@acme.com"),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.person_lookup._get_persons_by_email")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_email_fallback_groups(
        self, _name, channel, traits_email, email_from, mock_get_persons, mock_get_by_email, mock_capture
    ):
        """Non-web channels stuff the email into distinct_id; org is resolved via the email->ClickHouse fallback."""
        from posthog.models.person.person import Person

        customer_email = traits_email or email_from
        person_org = Organization.objects.create(name="Acme")
        person_user = User.objects.create(email="login@acme.com", distinct_id="real-did-1")
        OrganizationMembership.objects.create(user=person_user, organization=person_org)

        # distinct_id (the email) resolves no identified person...
        mock_get_persons.return_value = []
        # ...but the ClickHouse email lookup returns the person with their real distinct_id
        person = Person(team_id=self.team.id, is_identified=True)
        person._distinct_ids = ["real-did-1"]
        mock_get_by_email.return_value = {customer_email: person}

        traits = {"name": "Biz"}
        if traits_email:
            traits["email"] = traits_email

        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="",
            distinct_id=customer_email,
            channel_source=channel,
            anonymous_traits=traits,
            email_from=email_from,
        )

        capture_ticket_created(ticket)

        mock_get_by_email.assert_called_once_with(self.team, [customer_email])
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is True
        groups = call_kwargs["properties"]["$groups"]
        assert groups["organization"] == str(person_org.id)
        assert groups["project"] == str(self.team.uuid)

    @parameterized.expand(
        [
            ("no_person_for_email", False),
            ("person_without_membership", True),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.person_lookup._get_persons_by_email")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_email_fallback_no_groups(
        self, _name, person_found, mock_get_persons, mock_get_by_email, mock_capture
    ):
        from posthog.models.person.person import Person

        customer_email = "biz@acme.com"
        mock_get_persons.return_value = []

        if person_found:
            person = Person(team_id=self.team.id, is_identified=True)
            person._distinct_ids = ["real-did-1"]
            mock_get_by_email.return_value = {customer_email: person}
            # User exists but has no organization membership
            User.objects.create(email="login@acme.com", distinct_id="real-did-1")
        else:
            mock_get_by_email.return_value = {}

        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="",
            distinct_id=customer_email,
            channel_source="email",
            anonymous_traits={"name": "Biz", "email": customer_email},
        )

        capture_ticket_created(ticket)

        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is False
        assert "$groups" not in call_kwargs["properties"]

    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.person_lookup._get_persons_by_email")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_identified_person_without_membership_skips_email_fallback(
        self, mock_get_persons, mock_get_by_email, mock_capture
    ):
        """An identified person resolved via distinct_id is authoritative: no email fallback even if traits.email could match another org."""
        from posthog.models.person.person import Person

        # The widget distinct_id resolves to an identified person, but they have no org membership.
        mock_get_persons.return_value = [Person(team_id=self.team.id, is_identified=True)]

        capture_ticket_created(self.ticket)

        mock_get_by_email.assert_not_called()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is False
        assert "$groups" not in call_kwargs["properties"]

    @parameterized.expand(
        [
            # Channels NOT in the email-fallback allowlist must never run the email lookup.
            ("widget_anonymous_spoofed_email", "widget"),
            ("github_no_email", "github"),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.person_lookup._get_persons_by_email")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_non_verified_channels_skip_email_fallback(
        self, _name, channel, mock_get_persons, mock_get_by_email, mock_capture
    ):
        """anonymous_traits.email is attacker-controlled on the public widget, so it must never resolve an org.

        Even when an anonymous distinct_id resolves to no identified person and a victim org exists for the
        supplied email, non-allowlisted channels (widget, github) skip the email lookup entirely.
        """
        # A victim org/person that the spoofed email would resolve to if the lookup ran.
        victim_org = Organization.objects.create(name="Victim Corp")
        victim_user = User.objects.create(email="victim@bigcorp.com", distinct_id="victim-did")
        OrganizationMembership.objects.create(user=victim_user, organization=victim_org)

        # Anonymous distinct_id resolves to no identified person -> step 1 does not early-return.
        mock_get_persons.return_value = []

        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="",
            distinct_id="anon-attacker",
            channel_source=channel,
            anonymous_traits={"name": "Attacker", "email": "victim@bigcorp.com"},
        )

        capture_ticket_created(ticket)

        mock_get_by_email.assert_not_called()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is False
        assert "$groups" not in call_kwargs["properties"]

    @parameterized.expand(
        [
            ("with_customer", "cus_456"),
            ("without_customer", ""),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    @patch("posthog.hogql.query.execute_hogql_query")
    @patch("products.conversations.backend.events.get_group_types_for_project")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_analytics_fallback_groups(
        self, _name, customer_key, mock_get_persons, mock_group_types, mock_hogql, mock_capture
    ):
        """Cross-region account: no membership row in this region's Postgres, org resolved from event $groups."""
        from posthog.models.person.person import Person

        mock_get_persons.return_value = [Person(team_id=self.team.id, is_identified=True)]
        mock_group_types.return_value = [
            {"group_type": "project", "group_type_index": 0},
            {"group_type": "organization", "group_type_index": 1},
            {"group_type": "customer", "group_type_index": 2},
        ]
        mock_hogql.return_value.results = [["org-eu-123", customer_key]]

        capture_ticket_created(self.ticket)

        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is True
        groups = call_kwargs["properties"]["$groups"]
        assert groups["organization"] == "org-eu-123"
        # instance/project are rebuilt server-side, never taken from the event row
        assert groups["project"] == str(self.team.uuid)
        assert "instance" in groups
        if customer_key:
            assert groups["customer"] == customer_key
        else:
            assert "customer" not in groups

    @parameterized.expand(
        [
            ("no_events", []),
            ("empty_org_key", [["", ""]]),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    @patch("posthog.hogql.query.execute_hogql_query")
    @patch("products.conversations.backend.events.get_group_types_for_project")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_analytics_fallback_no_groups(
        self, _name, results, mock_get_persons, mock_group_types, mock_hogql, mock_capture
    ):
        from posthog.models.person.person import Person

        mock_get_persons.return_value = [Person(team_id=self.team.id, is_identified=True)]
        mock_group_types.return_value = [{"group_type": "organization", "group_type_index": 1}]
        mock_hogql.return_value.results = results

        capture_ticket_created(self.ticket)

        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is False
        assert "$groups" not in call_kwargs["properties"]

    @patch("products.conversations.backend.events.capture_internal")
    @patch("posthog.hogql.query.execute_hogql_query")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_membership_hit_skips_analytics_fallback(
        self, mock_get_persons, mock_hogql, mock_capture
    ):
        from posthog.models.person.person import Person

        person_org = Organization.objects.create(name="Person Org")
        person_user = User.objects.create(email="customer@example.com", distinct_id="customer-123")
        OrganizationMembership.objects.create(user=person_user, organization=person_org)

        mock_get_persons.return_value = [Person(team_id=self.team.id, is_identified=True)]

        capture_ticket_created(self.ticket)

        mock_hogql.assert_not_called()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["properties"]["$groups"]["organization"] == str(person_org.id)

    @patch("products.conversations.backend.events.capture_internal")
    @patch("posthog.hogql.query.execute_hogql_query")
    @patch("products.conversations.backend.events.get_group_types_for_project")
    @patch("products.conversations.backend.person_lookup._get_persons_by_email")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_email_channel_analytics_fallback_groups(
        self, mock_get_persons, mock_get_by_email, mock_group_types, mock_hogql, mock_capture
    ):
        """Email channel, person found by email, no membership in this region -> org from event $groups."""
        from posthog.models.person.person import Person

        customer_email = "biz@acme.com"
        mock_get_persons.return_value = []
        person = Person(team_id=self.team.id, is_identified=True)
        person._distinct_ids = ["real-did-1"]
        mock_get_by_email.return_value = {customer_email: person}

        mock_group_types.return_value = [{"group_type": "organization", "group_type_index": 0}]
        mock_hogql.return_value.results = [["org-eu-123", ""]]

        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="",
            distinct_id=customer_email,
            channel_source="email",
            anonymous_traits={"name": "Biz", "email": customer_email},
        )

        capture_ticket_created(ticket)

        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is True
        assert call_kwargs["properties"]["$groups"]["organization"] == "org-eu-123"

    @parameterized.expand(
        [
            ("positive", [["org-eu-123", ""]], True),
            ("negative", [], False),
        ]
    )
    @patch("products.conversations.backend.events.capture_internal")
    @patch("posthog.hogql.query.execute_hogql_query")
    @patch("products.conversations.backend.events.get_group_types_for_project")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_analytics_fallback_result_is_cached(
        self, _name, results, expect_groups, mock_get_persons, mock_group_types, mock_hogql, mock_capture
    ):
        from posthog.models.person.person import Person

        mock_get_persons.return_value = [Person(team_id=self.team.id, is_identified=True)]
        mock_group_types.return_value = [{"group_type": "organization", "group_type_index": 0}]
        mock_hogql.return_value.results = results

        capture_ticket_created(self.ticket)
        capture_message_received(self.ticket, "msg-456", "Hello support")

        mock_hogql.assert_called_once()
        assert mock_capture.call_count == 2
        for call in mock_capture.call_args_list:
            if expect_groups:
                assert call.kwargs["properties"]["$groups"]["organization"] == "org-eu-123"
            else:
                assert "$groups" not in call.kwargs["properties"]

    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.events.get_persons_by_distinct_ids")
    def test_capture_ticket_created_persists_organization_id(self, mock_get_persons, mock_capture):
        from posthog.models.person.person import Person

        person_org = Organization.objects.create(name="Persist Org")
        person_user = User.objects.create(email="persist@example.com", distinct_id="customer-123")
        OrganizationMembership.objects.create(user=person_user, organization=person_org)

        mock_get_persons.return_value = [Person(team_id=self.team.id, is_identified=True)]

        assert self.ticket.organization_id is None
        capture_ticket_created(self.ticket)

        self.ticket.refresh_from_db()
        assert self.ticket.organization_id == str(person_org.id)

    @patch("products.conversations.backend.events.capture_internal")
    @patch("products.conversations.backend.events._resolve_org_groups")
    def test_capture_message_received_uses_stored_organization_id(self, mock_resolve, mock_capture):
        self.ticket.organization_id = "stored-org-123"
        self.ticket.save(update_fields=["organization_id"])

        capture_message_received(self.ticket, "msg-456", "Hello support")

        mock_resolve.assert_not_called()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["process_person_profile"] is True
        groups = call_kwargs["properties"]["$groups"]
        assert groups["organization"] == "stored-org-123"
        assert groups["project"] == str(self.team.uuid)
        assert groups["instance"] == SITE_URL

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_ticket_status_changed_system_actor_uses_customer_distinct_id(self, mock_capture):
        """System actions (e.g. snooze wake) use the customer's distinct_id, not an actor's."""
        capture_ticket_status_changed(self.ticket, "on_hold", "open", actor_type="system")

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["distinct_id"] == self.ticket.distinct_id
        assert call_kwargs["properties"]["actor_type"] == "system"
        assert call_kwargs["properties"]["actor_id"] is None
        assert call_kwargs["properties"]["actor_email"] is None

    @patch("products.conversations.backend.events.capture_internal")
    def test_capture_ticket_status_changed_external_actor_uses_customer_distinct_id(self, mock_capture):
        """External actions (e.g. GitHub sync) use the customer's distinct_id."""
        capture_ticket_status_changed(self.ticket, "open", "resolved", actor_type="external")

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args.kwargs
        assert call_kwargs["distinct_id"] == self.ticket.distinct_id
        assert call_kwargs["properties"]["actor_type"] == "external"
        assert call_kwargs["properties"]["actor_id"] is None
        assert call_kwargs["properties"]["actor_email"] is None


class TestResolveGroupsFromAnalyticsClickHouse(ClickhouseTestMixin, APIBaseTest):
    """End-to-end coverage of the cross-region fallback against real ClickHouse events.

    The fallback exists to recover an org from a customer's analytics events when the
    region-local OrganizationMembership lookup misses. These events carry $group_N but
    deliberately NO $groupidentify — the common case where an app calls
    posthog.group(type, key) without properties — to prove resolution doesn't depend on
    $groupidentify and reads the org/customer group columns by their per-project index.
    """

    def setUp(self):
        super().setUp()
        cache.clear()

    @patch(
        "products.conversations.backend.events.get_group_types_for_project",
        return_value=[
            {"group_type": "project", "group_type_index": 0},
            {"group_type": "organization", "group_type_index": 1},
            {"group_type": "customer", "group_type_index": 2},
        ],
    )
    def test_resolves_groups_from_event_columns_without_groupidentify(self, _mock_group_types):
        # Plain $pageview events (not $groupidentify) stamped with the customer's groups.
        # Org is at index 1, customer at index 2 — proving column selection follows the
        # project's group-type mapping rather than assuming $group_0.
        for _ in range(3):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="eu-user-did",
                properties={"$group_1": "org-eu-123", "$group_2": "cus_456"},
            )
        flush_persons_and_events()

        groups = _resolve_groups_from_analytics(self.team, ["eu-user-did"])

        assert groups == {
            "instance": SITE_URL,
            "project": str(self.team.uuid),
            "organization": "org-eu-123",
            "customer": "cus_456",
        }

    @patch(
        "products.conversations.backend.events.get_group_types_for_project",
        return_value=[
            {"group_type": "project", "group_type_index": 0},
            {"group_type": "organization", "group_type_index": 1},
        ],
    )
    def test_resolves_org_without_customer_group_type(self, _mock_group_types):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="eu-user-did",
            properties={"$group_1": "org-eu-123"},
        )
        flush_persons_and_events()

        groups = _resolve_groups_from_analytics(self.team, ["eu-user-did"])

        assert groups == {"instance": SITE_URL, "project": str(self.team.uuid), "organization": "org-eu-123"}

    @patch(
        "products.conversations.backend.events.get_group_types_for_project",
        return_value=[
            {"group_type": "project", "group_type_index": 0},
            {"group_type": "organization", "group_type_index": 1},
        ],
    )
    def test_no_org_group_on_events_returns_none(self, _mock_group_types):
        # Events exist but never carried an organization group → nothing to recover.
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="eu-user-did",
            properties={"$group_0": "project:1"},
        )
        flush_persons_and_events()

        assert _resolve_groups_from_analytics(self.team, ["eu-user-did"]) is None

    @patch(
        "products.conversations.backend.events.get_group_types_for_project",
        return_value=[{"group_type": "organization", "group_type_index": 1}],
    )
    def test_lookup_is_scoped_to_the_passed_distinct_ids(self, _mock_group_types):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="someone-else",
            properties={"$group_1": "org-other"},
        )
        flush_persons_and_events()

        assert _resolve_groups_from_analytics(self.team, ["eu-user-did"]) is None
