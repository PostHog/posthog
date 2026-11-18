from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role
from products.conversations.backend.ai.suggest import (
    _build_ticket_context,
    _format_enhanced_context,
    format_conversation,
)
from products.conversations.backend.ai.ticket_context import (
    MAX_PRIOR_TICKET_REPLY_CHARS,
    MAX_SESSION_CONTEXT_SECTION_CHARS,
    PriorTicket,
    format_account_properties,
    format_prior_tickets,
    format_session_context,
    parse_posthog_entity_refs,
)
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import TicketStatus
from products.customer_analytics.backend.facade.testing import (
    create_account,
    create_custom_property_definition,
    create_custom_property_value,
)

# Prior tickets are ordered by created_at, so the tests only need a stable point to count
# back from. A real clock makes the same assertions flaky when CI runs near midnight UTC.
_FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)


class TestFormatEnhancedContext(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "canonical array properties",
                {"properties.$exception_types": ["TypeError"], "properties.$exception_values": ["Bad call"]},
            ),
            (
                "legacy scalar properties",
                {"properties.$exception_type": "TypeError", "properties.$exception_message": "Bad call"},
            ),
        ]
    )
    def test_formats_exception_type_and_message(self, _name: str, exception: dict[str, object]) -> None:
        context = _format_enhanced_context("Conversation", [], [exception])

        assert "TypeError: Bad call" in context


class TestFormatConversation(SimpleTestCase):
    @parameterized.expand(
        [
            ("customer", {"author_type": "customer", "is_private": False}, "[Customer]: hi"),
            ("human_public", {"author_type": "team", "is_private": False}, "[Support]: hi"),
            ("human_private", {"author_type": "team", "is_private": True}, "[Support (private note)]: hi"),
            ("ai_public", {"author_type": "AI", "is_private": False}, "[AI assistant]: hi"),
            ("ai_private", {"author_type": "AI", "is_private": True}, "[AI (private note)]: hi"),
        ]
    )
    def test_author_labels(self, _name: str, item_context: dict[str, object], expected: str) -> None:
        ticket = MagicMock()
        ticket.session_context = None
        message = MagicMock()
        message.item_context = item_context
        message.content = "hi"
        assert expected in format_conversation(ticket, [message])


class TestFormatSessionContext(SimpleTestCase):
    def test_renders_allowlisted_fields(self) -> None:
        text = format_session_context(
            {
                "current_url": "https://app.example.com/billing",
                "sdk_version": "1.2.3",
                "browser": "Chrome",
                "replay_url": "https://us.posthog.com/replay/abc",
                "email": "user@example.com",
                "distinct_id": "pii-distinct",
            }
        )
        assert "Page: https://app.example.com/billing" in text
        assert "SDK version: 1.2.3" in text
        assert "Browser: Chrome" in text
        assert "replay" not in text
        assert "user@example.com" not in text
        assert "pii-distinct" not in text

        long_url = "https://app.example.com/" + "x" * 2000
        capped = format_session_context({"current_url": long_url})
        assert len(capped) <= MAX_SESSION_CONTEXT_SECTION_CHARS
        assert "..." in capped

    def test_accepts_posthog_prefixed_keys(self) -> None:
        text = format_session_context({"$lib_version": "1.0.0", "$browser": "Firefox", "$os": "macOS"})
        assert "SDK version: 1.0.0" in text
        assert "Browser: Firefox" in text
        assert "OS: macOS" in text

    def test_does_not_treat_lib_name_as_sdk_version(self) -> None:
        text = format_session_context({"$lib": "web", "$lib_version": "1.2.3"})
        assert "SDK version: 1.2.3" in text
        assert "web" not in text

    def test_skips_non_dict(self) -> None:
        assert format_session_context(None) == ""
        assert format_session_context("nope") == ""


class TestParsePosthogEntityRefs(SimpleTestCase):
    def test_parses_urls_and_uuids(self) -> None:
        recording = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        other = "11111111-2222-3333-4444-555555555555"
        text = (
            f"See https://us.posthog.com/project/2/feature_flags/session-replay-enabled "
            f"and /insights/abc123XY /dashboard/42 /replay/{recording} also {other}"
        )
        parsed = parse_posthog_entity_refs(text)
        assert "Feature flag: session-replay-enabled" in parsed
        assert "Insight: abc123XY" in parsed
        assert "Dashboard: 42" in parsed
        assert f"Recording: {recording}" in parsed
        assert f"UUID: {other}" in parsed
        assert parsed.count(recording) == 1

    def test_skips_new_paths_and_bare_words(self) -> None:
        parsed = parse_posthog_entity_refs("Open /feature_flags/new and mention session-replay-enabled")
        assert parsed == ""


class TestFormatPriorTickets(SimpleTestCase):
    def test_truncates_reply_and_omits_identity_fields(self) -> None:
        reply = "x" * (MAX_PRIOR_TICKET_REPLY_CHARS + 50)
        text = format_prior_tickets([PriorTicket(ticket_number=12, title="#12: Billing", reply=reply)])
        assert "#12: Billing" in text
        assert "Final reply:" in text
        assert len(text) < MAX_PRIOR_TICKET_REPLY_CHARS + 80
        assert "user@example.com" not in text
        assert "distinct-secret" not in text


class TestFormatAccountProperties(SimpleTestCase):
    def test_renders_selected_values_and_skips_empty(self) -> None:
        text = format_account_properties([("Plan", "Enterprise"), ("Seats", 12.0), ("Empty", None), ("Flag", True)])
        assert "- Plan: Enterprise" in text
        assert "- Seats: 12" in text
        assert "- Flag: true" in text
        assert "Empty" not in text


class TestBuildTicketContext(BaseTest):
    def _create_ticket(self, **kwargs) -> Ticket:
        defaults = {
            "team": self.team,
            "widget_session_id": uuid4().hex,
            "distinct_id": "person-1",
        }
        defaults.update(kwargs)
        return Ticket.objects.create_with_number(**defaults)

    def _comment(self, ticket: Ticket, *, content: str, author_type: str, is_private: bool = False) -> Comment:
        return Comment.objects.create(
            team=self.team,
            created_by=self.user if author_type == "support" else None,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=content,
            item_context={"author_type": author_type, "is_private": is_private},
        )

    def _context(self, ticket: Ticket, messages: list[Comment] | None = None, team: Team | None = None) -> str:
        with patch("products.conversations.backend.ai.suggest._load_person_properties", return_value={}):
            return _build_ticket_context(ticket, messages or [], team or self.team)

    def test_prior_tickets_are_team_scoped_resolved_and_pii_free(self) -> None:
        current = self._create_ticket(distinct_id="same-person", organization_id="org-1")
        prior = self._create_ticket(
            distinct_id="same-person",
            organization_id="org-1",
            status=TicketStatus.RESOLVED,
            email_subject="Replay is blank",
            email_from="customer@example.com",
        )
        prior.created_at = _FIXED_NOW - timedelta(days=1)
        prior.save(update_fields=["created_at"])
        self._comment(prior, content="Enable session replay in project settings.", author_type="support")
        self._comment(prior, content="Private diagnosis", author_type="support", is_private=True)
        self._comment(prior, content="Customer said thanks", author_type="customer")

        open_ticket = self._create_ticket(distinct_id="same-person", status=TicketStatus.OPEN)
        self._comment(open_ticket, content="Not resolved yet", author_type="support")

        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_ticket = self._create_ticket(
            team=other_team,
            distinct_id="same-person",
            status=TicketStatus.RESOLVED,
        )
        Comment.objects.create(
            team=other_team,
            created_by=self.user,
            scope="conversations_ticket",
            item_id=str(other_ticket.id),
            content="Other team answer",
            item_context={"author_type": "support", "is_private": False},
        )

        message = self._comment(current, content="Replay is still blank", author_type="customer")
        context = self._context(current, [message])

        assert "Previous resolved tickets:" in context
        assert "Replay is blank" in context
        assert "Enable session replay in project settings." in context
        assert "Private diagnosis" not in context
        assert "Customer said thanks" not in context
        assert "Not resolved yet" not in context
        assert "Other team answer" not in context
        assert "customer@example.com" not in context
        assert "same-person" not in context

    def test_prior_tickets_match_organization_when_distinct_id_differs(self) -> None:
        current = self._create_ticket(distinct_id="person-a", organization_id="acct-99", identity_verified=True)
        prior = self._create_ticket(
            distinct_id="person-b",
            organization_id="acct-99",
            status=TicketStatus.RESOLVED,
            email_subject="SSO setup",
        )
        prior.created_at = _FIXED_NOW - timedelta(days=2)
        prior.save(update_fields=["created_at"])
        self._comment(prior, content="Use Google SSO.", author_type="support")
        context = self._context(current)
        assert "SSO setup" in context
        assert "Use Google SSO." in context

    @parameterized.expand(["everyone", "one member", "one role"])
    def test_prior_tickets_skip_a_ticket_a_member_may_not_open(self, restricted_for: str) -> None:
        # A rule on one ticket hides it from some agents, but the note quoting it is read by
        # everyone who can open the ticket being answered. So a restricted ticket stays out.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        current = self._create_ticket(distinct_id="same-person")
        restricted = self._create_ticket(
            distinct_id="same-person", status=TicketStatus.RESOLVED, email_subject="Escalation"
        )
        restricted.created_at = _FIXED_NOW - timedelta(days=1)
        restricted.save(update_fields=["created_at"])
        self._comment(restricted, content="Their restricted workaround.", author_type="support")
        open_to_all = self._create_ticket(
            distinct_id="same-person", status=TicketStatus.RESOLVED, email_subject="Password reset"
        )
        open_to_all.created_at = _FIXED_NOW - timedelta(days=2)
        open_to_all.save(update_fields=["created_at"])
        self._comment(open_to_all, content="Use the reset link.", author_type="support")

        # Control: with no rule both prior tickets reach the context.
        control = self._context(current)
        assert "Escalation" in control
        assert "Password reset" in control

        rule: dict = {
            "team": self.team,
            "resource": "ticket",
            "resource_id": str(restricted.id),
            "access_level": "none",
        }
        if restricted_for == "one member":
            agent = User.objects.create_and_join(self.organization, "agent@example.com", "testtest")
            rule["organization_member"] = OrganizationMembership.objects.get(user=agent, organization=self.organization)
        elif restricted_for == "one role":
            rule["role"] = Role.objects.create(organization=self.organization, name="Support")
        AccessControl.objects.create(**rule)

        context = self._context(current)
        assert "Escalation" not in context
        assert "Their restricted workaround." not in context
        # The neighbour is untouched, so the rule withheld one ticket rather than the section.
        assert "Password reset" in context
        assert "Use the reset link." in context

    def test_keeps_last_three_resolved_tickets(self) -> None:
        current = self._create_ticket(distinct_id="repeat")
        for index, subject in enumerate(["Oldest", "Keep 1", "Keep 2", "Keep 3"], start=1):
            prior = self._create_ticket(
                distinct_id="repeat",
                status=TicketStatus.RESOLVED,
                email_subject=subject,
            )
            prior.created_at = _FIXED_NOW - timedelta(days=5 - index)
            prior.save(update_fields=["created_at"])
            self._comment(prior, content=f"Reply {subject}", author_type="support")
        context = self._context(current)
        assert "Oldest" not in context
        assert "Keep 1" in context
        assert "Keep 2" in context
        assert "Keep 3" in context

    def test_final_reply_ignores_team_and_ai_author_types(self) -> None:
        current = self._create_ticket(distinct_id="same-person")
        prior = self._create_ticket(
            distinct_id="same-person",
            status=TicketStatus.RESOLVED,
            email_subject="Billing",
        )
        prior.created_at = _FIXED_NOW - timedelta(days=1)
        prior.save(update_fields=["created_at"])
        self._comment(prior, content="Team analytics type", author_type="team")
        self._comment(prior, content="Use the billing page.", author_type="human")
        self._comment(prior, content="AI draft", author_type="AI")
        context = self._context(current)
        assert "Use the billing page." in context
        assert "Team analytics type" not in context
        assert "AI draft" not in context

    def test_skips_resolved_tickets_without_a_public_human_reply(self) -> None:
        current = self._create_ticket(distinct_id="same-person")
        silent = self._create_ticket(
            distinct_id="same-person",
            status=TicketStatus.RESOLVED,
            email_subject="Silent",
        )
        silent.created_at = _FIXED_NOW - timedelta(days=1)
        silent.save(update_fields=["created_at"])
        self._comment(silent, content="Private only", author_type="support", is_private=True)
        answered = self._create_ticket(
            distinct_id="same-person",
            status=TicketStatus.RESOLVED,
            email_subject="Answered",
        )
        answered.created_at = _FIXED_NOW - timedelta(days=2)
        answered.save(update_fields=["created_at"])
        self._comment(answered, content="Here is the fix.", author_type="support")
        context = self._context(current)
        assert "Silent" not in context
        assert "Answered" in context
        assert "Here is the fix." in context

    def test_prior_reply_stored_on_parent_team_for_child_environment(self) -> None:
        child = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
        )
        current = self._create_ticket(team=child, distinct_id="same-person")
        prior = self._create_ticket(
            team=child,
            distinct_id="same-person",
            status=TicketStatus.RESOLVED,
            email_subject="SSO setup",
        )
        prior.created_at = _FIXED_NOW - timedelta(days=1)
        prior.save(update_fields=["created_at"])
        comment = Comment.objects.create(
            team=child,
            created_by=self.user,
            scope="conversations_ticket",
            item_id=str(prior.id),
            content="Use Google SSO.",
            item_context={"author_type": "support", "is_private": False},
        )
        context = self._context(current, team=child)
        assert comment.team_id == self.team.id
        assert "SSO setup" in context
        assert "Use Google SSO." in context

    def test_last_message_text_is_not_used_as_prior_title(self) -> None:
        current = self._create_ticket(distinct_id="same-person")
        prior = self._create_ticket(
            distinct_id="same-person",
            status=TicketStatus.RESOLVED,
            last_message_text="email me at customer@example.com",
        )
        prior.created_at = _FIXED_NOW - timedelta(days=1)
        prior.save(update_fields=["created_at"])
        self._comment(prior, content="Reset the API key.", author_type="support")
        prior.last_message_text = "email me at customer@example.com"
        prior.save(update_fields=["last_message_text"])
        context = self._context(current)
        assert "customer@example.com" not in context
        assert "Reset the API key." in context

    def test_unattested_organization_never_keys_another_accounts_context(self) -> None:
        # organization_id resolves from client-supplied person properties, so a widget visitor can
        # claim any organization group key in the project. Without identity verification or a
        # team-mapped Slack channel, that claim must not reach another account's content.
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan", target_type="account")
        account = create_account(team_id=self.team.id, name="Acme", external_id="acct-1")
        create_custom_property_value(team_id=self.team.id, account=account, definition=plan, value_str="Enterprise")
        self.team.conversations_settings = {"ai_context_account_property_ids": [str(plan.id)]}
        self.team.save(update_fields=["conversations_settings"])

        victim = self._create_ticket(
            distinct_id="victim",
            organization_id="acct-1",
            status=TicketStatus.RESOLVED,
            email_subject="Their SSO setup",
        )
        victim.created_at = _FIXED_NOW - timedelta(days=1)
        victim.save(update_fields=["created_at"])
        self._comment(victim, content="Their private workaround.", author_type="support")

        spoofed = self._create_ticket(distinct_id="attacker", organization_id="acct-1")
        context = self._context(spoofed)
        assert "Their SSO setup" not in context
        assert "Their private workaround." not in context
        assert "Account properties:" not in context

        spoofed.identity_verified = True
        spoofed.save(update_fields=["identity_verified"])
        attested = self._context(spoofed)
        assert "Their SSO setup" in attested
        assert "- Plan: Enterprise" in attested

    def test_entity_refs_only_in_posthog_docs_mode(self) -> None:
        ticket = self._create_ticket()
        message = self._comment(
            ticket,
            content="Broken flag https://us.posthog.com/project/2/feature_flags/my-flag",
            author_type="customer",
        )
        generic = self._context(ticket, [message])
        assert "Referenced PostHog entities:" not in generic

        self.team.conversations_settings = {"docs_source": "posthog"}
        self.team.save(update_fields=["conversations_settings"])
        posthog = self._context(ticket, [message])
        assert "Feature flag: my-flag" in posthog

    def test_session_context_is_rendered(self) -> None:
        ticket = self._create_ticket(
            session_context={"current_url": "https://app.example.com/x", "sdk_version": "9.9.9", "browser": "Safari"}
        )
        context = self._context(ticket)
        assert "Page: https://app.example.com/x" in context
        assert "SDK version: 9.9.9" in context
        assert "Browser: Safari" in context

    def test_account_properties_only_selected_and_skip_missing(self) -> None:
        account = create_account(team_id=self.team.id, name="Acme", external_id="acct-1")
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan", target_type="account")
        seats = create_custom_property_definition(team_id=self.team.id, name="Seats", target_type="account")
        deleted = create_custom_property_definition(team_id=self.team.id, name="Deleted", target_type="account")
        create_custom_property_value(team_id=self.team.id, account=account, definition=plan, value_str="Enterprise")
        create_custom_property_value(team_id=self.team.id, account=account, definition=seats, value_str="50")
        deleted.delete()

        self.team.conversations_settings = {
            "ai_context_account_property_ids": [str(plan.id), str(deleted.id), str(uuid4())]
        }
        self.team.save(update_fields=["conversations_settings"])
        ticket = self._create_ticket(organization_id="acct-1", identity_verified=True)
        context = self._context(ticket)
        assert "- Plan: Enterprise" in context
        assert "Seats" not in context
        assert "Deleted" not in context

    @parameterized.expand(["everyone", "one member", "one role"])
    def test_account_properties_need_account_access_for_every_member(self, restricted: str) -> None:
        # The section goes into a note that every agent with ticket access reads, and the reply run
        # can't tell them apart. So a member the team kept out of Customer analytics must not be
        # handed account data here, however the team wrote that restriction.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        account = create_account(team_id=self.team.id, name="Acme", external_id="acct-1")
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan", target_type="account")
        create_custom_property_value(team_id=self.team.id, account=account, definition=plan, value_str="Enterprise")
        self.team.conversations_settings = {"ai_context_account_property_ids": [str(plan.id)]}
        self.team.save(update_fields=["conversations_settings"])
        ticket = self._create_ticket(organization_id="acct-1", identity_verified=True)

        # Control: with no rule the team default gives every member account access.
        assert "- Plan: Enterprise" in self._context(ticket)

        rule: dict = {
            "team": self.team,
            "resource": "customer_analytics",
            "resource_id": None,
            "access_level": "none",
        }
        if restricted == "one member":
            agent = User.objects.create_and_join(self.organization, "agent@example.com", "testtest")
            rule["organization_member"] = OrganizationMembership.objects.get(user=agent, organization=self.organization)
        elif restricted == "one role":
            rule["role"] = Role.objects.create(organization=self.organization, name="Support")
        AccessControl.objects.create(**rule)

        withheld = self._context(ticket)
        assert "Account properties:" not in withheld
        assert "Enterprise" not in withheld

    def test_account_properties_skip_an_account_a_member_may_not_open(self) -> None:
        # A rule on one account is the object-level twin of the resource-level case above: the
        # team kept this account from someone, so its properties stay out of a note they read.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        account = create_account(team_id=self.team.id, name="Acme", external_id="acct-1")
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan", target_type="account")
        create_custom_property_value(team_id=self.team.id, account=account, definition=plan, value_str="Enterprise")
        self.team.conversations_settings = {"ai_context_account_property_ids": [str(plan.id)]}
        self.team.save(update_fields=["conversations_settings"])
        ticket = self._create_ticket(organization_id="acct-1", identity_verified=True)

        # Control: the resource is open to everyone, so the section renders.
        assert "- Plan: Enterprise" in self._context(ticket)

        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(account.id),
            access_level="none",
        )
        restricted = self._context(ticket)
        assert "Account properties:" not in restricted
        assert "Enterprise" not in restricted

    def test_skips_account_section_when_account_missing_or_ca_errors(self) -> None:
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan", target_type="account")
        self.team.conversations_settings = {"ai_context_account_property_ids": [str(plan.id)]}
        self.team.save(update_fields=["conversations_settings"])
        ticket = self._create_ticket(organization_id="missing-acct", identity_verified=True)
        context = self._context(ticket)
        assert "Account properties:" not in context

        ticket.organization_id = "acct-err"
        ticket.save(update_fields=["organization_id"])
        with patch("products.conversations.backend.ai.ticket_context.get_account", side_effect=RuntimeError("down")):
            failed = self._context(ticket)
        assert "Account properties:" not in failed
