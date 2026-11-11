import re
from uuid import uuid4

from posthog.test.base import BaseTest

from django.test import Client, SimpleTestCase

from parameterized import parameterized

from posthog.admin.console.organization_tools import BulkDeactivateOrganizationsForm
from posthog.models import Organization, User


class TestBulkDeactivateOrganizationsForm(SimpleTestCase):
    def test_defaults_to_desktop_abuse_reason_and_parses_pasted_ids(self) -> None:
        first_organization_id = uuid4()
        second_organization_id = uuid4()
        form = BulkDeactivateOrganizationsForm(
            {
                "organization_ids": f"{first_organization_id},\n{second_organization_id} {first_organization_id}",
                "reason": Organization.DeactivationReason.DESKTOP_ABUSE.value,
                "custom_reason": "",
            }
        )

        assert (
            BulkDeactivateOrganizationsForm().fields["reason"].initial == Organization.DeactivationReason.DESKTOP_ABUSE
        )
        assert form.is_valid()
        assert form.cleaned_data["organization_ids"] == [first_organization_id, second_organization_id]
        assert form.cleaned_data["resolved_reason"] == Organization.DeactivationReason.DESKTOP_ABUSE.value

    def test_custom_reason_is_required_when_custom_is_selected(self) -> None:
        organization_id = uuid4()
        form = BulkDeactivateOrganizationsForm(
            {
                "organization_ids": str(organization_id),
                "reason": BulkDeactivateOrganizationsForm.CUSTOM_REASON,
                "custom_reason": "",
            }
        )

        assert not form.is_valid()
        assert "custom_reason" in form.errors

    def test_rejects_invalid_uuid(self) -> None:
        organization_id = uuid4()
        form = BulkDeactivateOrganizationsForm(
            {
                "organization_ids": f"{organization_id},not-a-uuid",
                "reason": Organization.DeactivationReason.DESKTOP_ABUSE.value,
                "custom_reason": "",
            }
        )

        assert not form.is_valid()
        assert "organization_ids" in form.errors

    def test_rejects_more_than_max_organization_ids(self) -> None:
        form = BulkDeactivateOrganizationsForm(
            {
                "organization_ids": "\n".join(
                    str(uuid4()) for _ in range(BulkDeactivateOrganizationsForm.MAX_ORGANIZATIONS + 1)
                ),
                "reason": Organization.DeactivationReason.DESKTOP_ABUSE.value,
                "custom_reason": "",
            }
        )

        assert not form.is_valid()
        assert "organization_ids" in form.errors


TOOL_URL = "/admin/console/tools/bulk-deactivate-organizations/deactivate/"
DESKTOP_ABUSE = Organization.DeactivationReason.DESKTOP_ABUSE.value
COMPLIANCE_REVIEW = Organization.DeactivationReason.COMPLIANCE_REVIEW.value


class TestBulkDeactivateOrganizationsTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _preview(self, organization_ids: str, reason: str = DESKTOP_ABUSE, custom_reason: str = ""):
        return self.client.post(
            TOOL_URL, {"organization_ids": organization_ids, "reason": reason, "custom_reason": custom_reason}
        )

    def _confirm_token(self, preview_response) -> str:
        match = re.search(r'name="confirm_token" value="([^"]+)"', preview_response.content.decode())
        assert match is not None, "The preview page has no confirm button"
        return match.group(1)

    def _deactivate(self, organization_ids: str, reason: str = DESKTOP_ABUSE, custom_reason: str = ""):
        token = self._confirm_token(self._preview(organization_ids, reason, custom_reason))
        return self.client.post(TOOL_URL, {"confirm_token": token})

    def test_preview_shows_matched_organizations_and_missing_ids_without_deactivating(self) -> None:
        missing_id = uuid4()

        response = self._preview(f"{self.organization.id}\n{missing_id}")

        assert response.status_code == 200
        self.organization.refresh_from_db()
        assert self.organization.is_active
        assert str(self.organization.id) in response.content.decode()
        assert str(missing_id) in response.content.decode()

    @parameterized.expand(
        [
            ("preset_reason", DESKTOP_ABUSE, "", DESKTOP_ABUSE),
            (
                "custom_reason",
                BulkDeactivateOrganizationsForm.CUSTOM_REASON,
                "Manual review required.",
                "Manual review required.",
            ),
        ]
    )
    def test_confirm_deactivates_active_organizations_and_keeps_inactive_ones(
        self, _name: str, reason: str, custom_reason: str, expected_reason: str
    ) -> None:
        inactive = Organization.objects.create(
            name="Already inactive", is_active=False, is_not_active_reason=COMPLIANCE_REVIEW
        )

        response = self._deactivate(f"{self.organization.id}\n{inactive.id}\n{uuid4()}", reason, custom_reason)

        assert response.status_code == 302
        self.organization.refresh_from_db()
        inactive.refresh_from_db()
        assert (self.organization.is_active, self.organization.is_not_active_reason) == (False, expected_reason)
        assert (inactive.is_active, inactive.is_not_active_reason) == (False, COMPLIANCE_REVIEW)

    def test_confirm_keeps_the_reason_of_an_organization_deactivated_since_the_preview(self) -> None:
        token = self._confirm_token(self._preview(str(self.organization.id)))
        Organization.objects.filter(id=self.organization.id).update(
            is_active=False, is_not_active_reason=COMPLIANCE_REVIEW
        )

        self.client.post(TOOL_URL, {"confirm_token": token})

        self.organization.refresh_from_db()
        assert self.organization.is_not_active_reason == COMPLIANCE_REVIEW

    def test_preview_requires_at_least_one_active_organization(self) -> None:
        inactive = Organization.objects.create(name="Only inactive", is_active=False)

        response = self._preview(str(inactive.id))

        assert response.status_code == 400
        assert "All matched organizations are already inactive." in response.content.decode()

    @parameterized.expand([("tampered_token", "tampered"), ("another_staff_member", "other_user")])
    def test_confirm_refuses_a_token_it_did_not_issue_for_this_user(self, _name: str, case: str) -> None:
        token = self._confirm_token(self._preview(str(self.organization.id)))
        client = self.client
        if case == "tampered":
            token = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
        else:
            other = User.objects.create_and_join(self.organization, "other-staff@posthog.com", None, is_staff=True)
            client = Client()
            client.force_login(other)

        response = client.post(TOOL_URL, {"confirm_token": token})

        assert response.status_code == 302
        assert response["Location"] == TOOL_URL
        self.organization.refresh_from_db()
        assert self.organization.is_active
