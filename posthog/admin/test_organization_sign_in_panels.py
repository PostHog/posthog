from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.admin.models import LogEntry
from django.test import Client, SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.admin.console.member_email_migration import RequestedEmailChange
from posthog.admin.console.organization_sign_in_panels import ChangeMemberEmailsForm
from posthog.models import Organization, OrganizationDomain, User
from posthog.session.models import Session

_PAIR = [("ada@old.example.com", "a.lovelace@new.example.com")]


class TestChangeMemberEmailsForm(SimpleTestCase):
    @parameterized.expand(
        [
            ("current_only", "ada@old.example.com", [("ada@old.example.com", None)]),
            ("space", "ada@old.example.com a.lovelace@new.example.com", _PAIR),
            ("comma", "ada@old.example.com,a.lovelace@new.example.com", _PAIR),
            ("tab", "ada@old.example.com\ta.lovelace@new.example.com", _PAIR),
            ("arrow", "ada@old.example.com -> a.lovelace@new.example.com", _PAIR),
            (
                "blank_lines_between_members",
                "ada@old.example.com\n\n  grace@old.example.com  \n",
                [("ada@old.example.com", None), ("grace@old.example.com", None)],
            ),
        ]
    )
    def test_reads_one_member_per_line(self, _name: str, members: str, expected: list[tuple[str, str | None]]) -> None:
        form = ChangeMemberEmailsForm({"members": members, "new_domain": "new.example.com", "reason": "IdP migration"})

        assert form.is_valid(), form.errors
        assert form.cleaned_data["members"] == [
            RequestedEmailChange(current_email=current, new_email=new) for current, new in expected
        ]

    @parameterized.expand(
        [
            ("three_addresses_on_a_line", "a@old.example.com b@new.example.com c@new.example.com", "", "members"),
            ("not_an_email", "ada", "new.example.com", "members"),
            ("no_members", "  \n ", "new.example.com", "members"),
            ("no_domain_for_a_line_without_a_new_email", "ada@old.example.com", "", "new_domain"),
        ]
    )
    def test_refuses_input_it_cannot_read(self, _name: str, members: str, new_domain: str, field: str) -> None:
        form = ChangeMemberEmailsForm({"members": members, "new_domain": new_domain, "reason": "IdP migration"})

        assert not form.is_valid()
        assert field in form.errors

    def test_new_domain_is_optional_when_every_line_has_a_new_email(self) -> None:
        form = ChangeMemberEmailsForm(
            {"members": "ada@old.example.com a.lovelace@new.example.com", "new_domain": "", "reason": "IdP migration"}
        )

        assert form.is_valid(), form.errors


@patch("posthog.admin.console.member_email_migration.send_email_change_emails.delay")
class TestChangeMemberEmails(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        for domain in ("old.example.com", "new.example.com"):
            OrganizationDomain.objects.create(organization=self.organization, domain=domain, verified_at=timezone.now())
        self.member = self._create_user("ada@old.example.com", first_name="Ada")
        self.url = f"/admin/console/organizations/{self.organization.pk}/sign-in/change-member-emails/"

    def _preview(self, members: str, new_domain: str = "new.example.com", notify: bool = True):
        data = {"members": members, "new_domain": new_domain, "reason": "IdP migration"}
        if notify:
            data["notify"] = "on"
        return self.client.post(self.url, data)

    def _change(self, members: str, new_domain: str = "new.example.com", notify: bool = True):
        preview = self._preview(members, new_domain, notify)
        assert preview.status_code == 200, preview.content.decode()
        return self.client.post(self.url, {"confirm_token": preview.context["confirm_token"]}, follow=True)

    def test_form_lists_members_on_verified_domains(self, _send: MagicMock) -> None:
        self._create_user("guest@other.example.com")

        response = self.client.get(self.url)

        assert response.status_code == 200
        assert response.context["form"].initial["members"] == "ada@old.example.com"

    def test_preview_shows_the_change_without_making_it(self, send: MagicMock) -> None:
        response = self._preview("ada@old.example.com")

        assert response.status_code == 200
        assert "ada@new.example.com" in response.content.decode()
        self.member.refresh_from_db()
        assert self.member.email == "ada@old.example.com"
        send.assert_not_called()

    def test_confirm_moves_the_account_to_the_new_email(self, send: MagicMock) -> None:
        User.objects.filter(pk=self.member.pk).update(pending_email="ada@elsewhere.example.com")
        UserSocialAuth.objects.create(user=self.member, provider="saml", uid="ada@old.example.com")
        Client().force_login(self.member)
        assert Session.objects.filter(user_id=self.member.pk).exists()

        response = self._change("ada@old.example.com")

        assert response.status_code == 200
        self.member.refresh_from_db()
        assert self.member.email == "ada@new.example.com"
        assert self.member.pending_email is None
        assert self.organization.members.filter(pk=self.member.pk).exists()
        assert not UserSocialAuth.objects.filter(user=self.member).exists()
        assert not Session.objects.filter(user_id=self.member.pk).exists()
        assert send.call_args.args[1:] == ("Ada", "ada@old.example.com", "ada@new.example.com")
        assert LogEntry.objects.filter(
            object_id=str(self.member.pk), user_id=self.user.pk, change_message__contains="IdP migration"
        ).exists()

    def test_a_new_email_on_the_line_wins_over_the_new_domain(self, _send: MagicMock) -> None:
        self._change("ada@old.example.com A.Lovelace@new.example.com")

        self.member.refresh_from_db()
        assert self.member.email == "a.lovelace@new.example.com"

    def test_sends_no_email_when_notify_is_off(self, send: MagicMock) -> None:
        self._change("ada@old.example.com", notify=False)

        self.member.refresh_from_db()
        assert self.member.email == "ada@new.example.com"
        send.assert_not_called()

    @parameterized.expand(
        [
            ("new_domain_not_verified", "grace@old.example.com grace@unverified.example.com"),
            ("current_domain_not_verified", "grace@other.example.com"),
            ("new_email_taken_by_another_account", "grace@old.example.com taken@new.example.com"),
            ("new_email_taken_by_an_earlier_line", "grace@old.example.com ada@new.example.com"),
            ("new_email_too_long", f"grace@old.example.com {'g' * 250}@new.example.com"),
            ("not_a_member", "outsider@old.example.com"),
            ("staff_account", "staff@old.example.com"),
        ]
    )
    def test_skips_a_member_it_must_not_change(self, _send: MagicMock, _name: str, line: str) -> None:
        other_organization = Organization.objects.create(name="Other")
        User.objects.create_and_join(other_organization, "taken@new.example.com", None)
        User.objects.create_and_join(other_organization, "outsider@old.example.com", None)
        self._create_user("staff@old.example.com", is_staff=True)
        current_email = line.split()[0]
        if current_email.startswith("grace@"):
            self._create_user(current_email)

        response = self._change(f"ada@old.example.com\n{line}")

        assert "Skipped" in response.content.decode()
        assert User.objects.filter(email=current_email).exists()
        self.member.refresh_from_db()
        assert self.member.email == "ada@new.example.com"

    @parameterized.expand(
        [
            ("another_case_matches_neither_account", "GRACE@old.example.com", None),
            ("the_stored_case_matches_that_account", "Grace@old.example.com", "mixed"),
        ]
    )
    def test_emails_that_differ_only_by_case_are_separate_accounts(
        self, _send: MagicMock, _name: str, typed: str, expected: str | None
    ) -> None:
        lower = self._create_user("grace@old.example.com")
        mixed = self._create_user("grace.two@old.example.com")
        User.objects.filter(pk=mixed.pk).update(email="Grace@old.example.com")

        self._change(f"ada@old.example.com\n{typed}")

        lower.refresh_from_db()
        mixed.refresh_from_db()
        assert lower.email == "grace@old.example.com"
        assert mixed.email == ("grace@new.example.com" if expected == "mixed" else "Grace@old.example.com")

    def test_a_failed_notice_keeps_the_history_and_the_rest_of_the_list(self, send: MagicMock) -> None:
        send.side_effect = RuntimeError("broker down")
        grace = self._create_user("grace@old.example.com")

        response = self._change("ada@old.example.com\ngrace@old.example.com")

        assert response.status_code == 200
        for member in (self.member, grace):
            member.refresh_from_db()
            assert member.email.endswith("@new.example.com")
            assert LogEntry.objects.filter(object_id=str(member.pk)).exists()

    def test_refuses_a_list_where_nothing_can_change(self, _send: MagicMock) -> None:
        response = self._preview("outsider@old.example.com")

        assert response.status_code == 400
        assert "confirm_token" not in response.context

    def test_is_not_offered_without_a_verified_domain(self, _send: MagicMock) -> None:
        OrganizationDomain.objects.filter(organization=self.organization).update(verified_at=None)

        response = self._preview("ada@old.example.com")

        assert response.status_code == 404
        self.member.refresh_from_db()
        assert self.member.email == "ada@old.example.com"
