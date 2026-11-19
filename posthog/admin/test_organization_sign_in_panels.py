from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group
from django.test import Client, SimpleTestCase

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.admin.console.member_email_migration import RequestedEmailChange
from posthog.admin.console.organization_sign_in_panels import PLATFORM_FEATURES, ChangeMemberEmailsForm
from posthog.models import Organization, OrganizationDomain, User
from posthog.models.id_jag_identity import IdJagIdentity
from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.session.models import Session

_PAIR = [("ada@old.example.com", "a.lovelace@new.example.com")]
VERIFIED_AT = "2024-01-01T00:00:00Z"


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
        Group.objects.get_or_create(name=PLATFORM_FEATURES.staff_group)[0].user_set.add(self.user)
        for domain in ("old.example.com", "new.example.com"):
            OrganizationDomain.objects.create(organization=self.organization, domain=domain, verified_at=VERIFIED_AT)
        self.member = self._create_user("ada@old.example.com", first_name="Ada")
        self.url = self._url("old--example--com")

    def _url(self, domain_key: str) -> str:
        return f"/admin/console/organizations/{self.organization.pk}/sign-in/change-emails-{domain_key}/"

    def _preview(self, members: str, new_domain: str = "new.example.com", notify: bool = True):
        data = {"members": members, "new_domain": new_domain, "reason": "IdP migration"}
        if notify:
            data["notify"] = "on"
        return self.client.post(self.url, data)

    def _change(self, members: str, new_domain: str = "new.example.com", notify: bool = True):
        preview = self._preview(members, new_domain, notify)
        assert preview.status_code == 200, preview.content.decode()
        return self.client.post(self.url, {"confirm_token": preview.context["confirm_token"]}, follow=True)

    def test_each_form_lists_the_members_on_its_domain(self, _send: MagicMock) -> None:
        self._create_user("guest@other.example.com")
        self._create_user("grace@new.example.com")
        self._create_user("staff@old.example.com", is_staff=True)
        # A domain that differs from old.example.com only by a hyphen in place of a dot.
        OrganizationDomain.objects.create(
            organization=self.organization, domain="old-example.com", verified_at=VERIFIED_AT
        )
        self._create_user("linus@old-example.com")

        old_domain = self.client.get(self.url)
        new_domain = self.client.get(self._url("new--example--com"))
        hyphen_domain = self.client.get(self._url("old-example--com"))

        assert old_domain.context["form"].initial["members"] == "ada@old.example.com"
        assert hyphen_domain.context["form"].initial["members"] == "linus@old-example.com"
        assert [value for value, _ in old_domain.context["form"].fields["new_domain"].choices] == [
            "",
            "new.example.com",
            "old-example.com",
        ]
        assert new_domain.context["form"].initial["members"] == "grace@new.example.com"

    def test_the_next_run_lists_the_members_the_last_one_did_not(self, _send: MagicMock) -> None:
        self._create_user("grace@old.example.com")

        with patch.object(ChangeMemberEmailsForm, "MAX_MEMBERS", 1):
            response = self.client.get(self.url)
            assert "lists the first 1" in response.context["operation"].description
            self._change(response.context["form"].initial["members"])

            assert self.client.get(self.url).context["form"].initial["members"] == "grace@old.example.com"

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

    def test_confirm_removes_the_bindings_to_this_organizations_identity_providers(self, _send: MagicMock) -> None:
        other_organization = Organization.objects.create(name="Other")
        bindings = {}
        for organization in (self.organization, other_organization):
            config = IdentityProviderConfig.objects.create(
                organization=organization, id_jag_issuer_url="https://idp.example.com"
            )
            bindings[organization.pk] = IdJagIdentity.objects.create(
                identity_provider_config=config, issuer="https://idp.example.com", subject="ada", user=self.member
            )

        self._change("ada@old.example.com")

        assert not IdJagIdentity.objects.filter(pk=bindings[self.organization.pk].pk).exists()
        assert IdJagIdentity.objects.filter(pk=bindings[other_organization.pk].pk).exists()

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

    def test_two_rows_cannot_take_emails_that_fold_onto_one_login(self, _send: MagicMock) -> None:
        grace = self._create_user("grace@old.example.com")

        self._change("ada@old.example.com i@new.example.com\ngrace@old.example.com \u0130@new.example.com")

        self.member.refresh_from_db()
        grace.refresh_from_db()
        assert self.member.email == "i@new.example.com"
        assert grace.email == "grace@old.example.com"

    def test_refuses_members_on_a_domain_that_provisions_accounts_automatically(self, _send: MagicMock) -> None:
        OrganizationDomain.objects.filter(domain="old.example.com").update(jit_provisioning_enabled=True)

        response = self._preview("ada@old.example.com")

        assert response.status_code == 400
        assert "Automatic provisioning is on for old.example.com" in response.content.decode()
        assert "confirm_token" not in response.context

    def test_an_email_that_differs_only_by_case_is_not_a_change(self, _send: MagicMock) -> None:
        grace = self._create_user("grace@new.example.com")
        User.objects.filter(pk=grace.pk).update(email="Grace@new.example.com")
        UserSocialAuth.objects.create(user=grace, provider="saml", uid="grace@new.example.com")

        response = self._change("ada@old.example.com\nGrace@new.example.com")

        assert "Skipped: Already uses this email" in response.content.decode()
        grace.refresh_from_db()
        assert grace.email == "Grace@new.example.com"
        assert UserSocialAuth.objects.filter(user=grace).exists()

    def test_a_failed_notice_keeps_the_history_and_the_rest_of_the_list(self, send: MagicMock) -> None:
        send.side_effect = RuntimeError("broker down")
        grace = self._create_user("grace@old.example.com")

        response = self._change("ada@old.example.com\ngrace@old.example.com")

        assert response.status_code == 200
        for member in (self.member, grace):
            member.refresh_from_db()
            assert member.email.endswith("@new.example.com")
            assert LogEntry.objects.filter(object_id=str(member.pk)).exists()

    @parameterized.expand(
        [
            ("no_listed_email_is_a_member", "outsider@old.example.com", "new.example.com", 400, "members"),
            ("the_new_domain_is_not_verified", "ada@old.example.com", "unverified.example.com", 400, "new_domain"),
        ]
    )
    def test_preview_refuses_only_what_it_cannot_change(
        self, _send: MagicMock, _name: str, members: str, new_domain: str, status: int, error_field: str | None
    ) -> None:
        response = self._preview(members, new_domain)

        assert response.status_code == status
        assert ("confirm_token" in response.context) == (status == 200)
        if error_field is not None:
            assert error_field in response.context["form"].errors

    def test_staff_outside_the_owning_group_cannot_run_it(self, _send: MagicMock) -> None:
        self.user.groups.clear()

        response = self.client.post(
            self.url, {"members": "ada@old.example.com", "new_domain": "new.example.com", "reason": "IdP migration"}
        )

        assert response.status_code == 403
        self.member.refresh_from_db()
        assert self.member.email == "ada@old.example.com"

    def test_is_not_offered_without_a_verified_domain(self, _send: MagicMock) -> None:
        OrganizationDomain.objects.filter(organization=self.organization).update(verified_at=None)

        response = self._preview("ada@old.example.com")

        assert response.status_code == 404
        self.member.refresh_from_db()
        assert self.member.email == "ada@old.example.com"
