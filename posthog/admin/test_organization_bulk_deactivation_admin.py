from uuid import uuid4

from posthog.test.base import BaseTest

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase

from posthog.admin.admins.organization_admin import BulkDeactivateOrganizationsForm, OrganizationAdmin
from posthog.models import Organization


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


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

    def test_preview_token_is_bound_to_ids_and_reason(self) -> None:
        organization_id = uuid4()
        form = BulkDeactivateOrganizationsForm(
            {
                "organization_ids": str(organization_id),
                "reason": Organization.DeactivationReason.DESKTOP_ABUSE.value,
                "custom_reason": "",
            }
        )

        assert form.is_valid()
        preview_token = form.preview_token()
        assert form.preview_token_matches(preview_token)

        changed_form = BulkDeactivateOrganizationsForm(
            {
                "organization_ids": str(organization_id),
                "reason": Organization.DeactivationReason.UNPAID_BALANCE.value,
                "custom_reason": "",
            }
        )

        assert changed_form.is_valid()
        assert not changed_form.preview_token_matches(preview_token)

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


class TestOrganizationAdminBulkDeactivate(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = OrganizationAdmin(Organization, AdminSite())

    def _post(self, data: dict[str, str]) -> HttpRequest:
        request = self.factory.post("/admin/posthog/organization/bulk-deactivate/", data)
        request.user = self.user
        _attach_messages(request)
        return request

    def _preview_token(self, organization_ids: str, reason: str, custom_reason: str = "") -> str:
        form = BulkDeactivateOrganizationsForm(
            {
                "organization_ids": organization_ids,
                "reason": reason,
                "custom_reason": custom_reason,
            }
        )
        assert form.is_valid()
        return form.preview_token()

    def test_preview_shows_matched_organizations_and_missing_ids_without_deactivating(self) -> None:
        missing_id = uuid4()
        request = self._post(
            {
                "organization_ids": f"{self.organization.id}\n{missing_id}",
                "reason": Organization.DeactivationReason.DESKTOP_ABUSE.value,
                "custom_reason": "",
                "preview": "1",
            }
        )

        response = self.admin.bulk_deactivate_view(request)

        assert response.status_code == 200
        self.organization.refresh_from_db()
        assert self.organization.is_active
        assert str(self.organization.id).encode() in response.content
        assert str(missing_id).encode() in response.content

    def test_confirm_deactivates_matched_organizations_with_selected_reason(self) -> None:
        other_organization = Organization.objects.create(name="Bulk deactivate target")
        missing_id = uuid4()
        organization_ids = f"{self.organization.id}\n{other_organization.id}\n{missing_id}"
        reason = Organization.DeactivationReason.DESKTOP_ABUSE.value
        request = self._post(
            {
                "organization_ids": organization_ids,
                "reason": reason,
                "custom_reason": "",
                "preview_token": self._preview_token(organization_ids, reason),
                "confirm": "1",
            }
        )

        response = self.admin.bulk_deactivate_view(request)

        assert response.status_code == 302
        for organization in (self.organization, other_organization):
            organization.refresh_from_db()
            assert organization.is_active is False
            assert organization.is_not_active_reason == Organization.DeactivationReason.DESKTOP_ABUSE.value

    def test_confirm_accepts_custom_reason(self) -> None:
        organization_ids = str(self.organization.id)
        custom_reason = "Manual review required."
        request = self._post(
            {
                "organization_ids": organization_ids,
                "reason": BulkDeactivateOrganizationsForm.CUSTOM_REASON,
                "custom_reason": custom_reason,
                "preview_token": self._preview_token(
                    organization_ids, BulkDeactivateOrganizationsForm.CUSTOM_REASON, custom_reason
                ),
                "confirm": "1",
            }
        )

        response = self.admin.bulk_deactivate_view(request)

        assert response.status_code == 302
        self.organization.refresh_from_db()
        assert self.organization.is_active is False
        assert self.organization.is_not_active_reason == "Manual review required."

    def test_confirm_skips_already_inactive_organizations(self) -> None:
        inactive_organization = Organization.objects.create(
            name="Already inactive target",
            is_active=False,
            is_not_active_reason=Organization.DeactivationReason.COMPLIANCE_REVIEW.value,
        )
        organization_ids = f"{self.organization.id}\n{inactive_organization.id}"
        reason = Organization.DeactivationReason.DESKTOP_ABUSE.value
        request = self._post(
            {
                "organization_ids": organization_ids,
                "reason": reason,
                "custom_reason": "",
                "preview_token": self._preview_token(organization_ids, reason),
                "confirm": "1",
            }
        )

        response = self.admin.bulk_deactivate_view(request)

        assert response.status_code == 302
        self.organization.refresh_from_db()
        inactive_organization.refresh_from_db()
        assert self.organization.is_active is False
        assert self.organization.is_not_active_reason == Organization.DeactivationReason.DESKTOP_ABUSE.value
        assert inactive_organization.is_active is False
        assert inactive_organization.is_not_active_reason == Organization.DeactivationReason.COMPLIANCE_REVIEW.value

    def test_preview_requires_at_least_one_active_organization(self) -> None:
        inactive_organization = Organization.objects.create(
            name="Only inactive target",
            is_active=False,
            is_not_active_reason=Organization.DeactivationReason.COMPLIANCE_REVIEW.value,
        )
        request = self._post(
            {
                "organization_ids": str(inactive_organization.id),
                "reason": Organization.DeactivationReason.DESKTOP_ABUSE.value,
                "custom_reason": "",
                "preview": "1",
            }
        )

        response = self.admin.bulk_deactivate_view(request)

        assert response.status_code == 200
        assert b"All matched organizations are already inactive." in response.content

    def test_confirm_requires_matching_preview_token(self) -> None:
        other_organization = Organization.objects.create(name="Unpreviewed target")
        reason = Organization.DeactivationReason.DESKTOP_ABUSE.value
        request = self._post(
            {
                "organization_ids": str(other_organization.id),
                "reason": reason,
                "custom_reason": "",
                "preview_token": self._preview_token(str(self.organization.id), reason),
                "confirm": "1",
            }
        )

        response = self.admin.bulk_deactivate_view(request)

        assert response.status_code == 200
        assert b"Review the organizations again before deactivating." in response.content
        self.organization.refresh_from_db()
        other_organization.refresh_from_db()
        assert self.organization.is_active
        assert other_organization.is_active

    def test_view_requires_change_permission(self) -> None:
        self.user.is_staff = False
        self.user.save()
        request = self._post(
            {
                "organization_ids": str(self.organization.id),
                "reason": Organization.DeactivationReason.DESKTOP_ABUSE.value,
                "custom_reason": "",
                "preview": "1",
            }
        )

        with self.assertRaises(PermissionDenied):
            self.admin.bulk_deactivate_view(request)
