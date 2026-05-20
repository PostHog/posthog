from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Organization, OrganizationMembership
from posthog.models.oauth import CIMDVerificationToken, create_cimd_verification_token


class TestCIMDVerificationTokenViewSet(APIBaseTest):
    def _url(self, detail_id: str | None = None) -> str:
        base = f"/api/organizations/{self.organization.id}/cimd_verification_tokens/"
        return f"{base}{detail_id}/" if detail_id else base

    def test_admin_can_create_and_sees_plaintext_once(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(self._url(), {"label": "Prod partner"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertTrue(body["value"].startswith("phvt_"))
        self.assertEqual(body["label"], "Prod partner")
        self.assertTrue(body["mask_value"].startswith("phvt"))
        self.assertIn("...", body["mask_value"])

        token = CIMDVerificationToken.objects.get(id=body["id"])
        self.assertEqual(token.organization_id, self.organization.id)
        self.assertEqual(token.created_by_id, self.user.id)
        self.assertNotEqual(token.secure_value, body["value"])

    def test_non_admin_cannot_create(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.post(self._url(), {"label": "blocked"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_returns_org_tokens_only_without_plaintext(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        create_cimd_verification_token(organization=self.organization, label="Ours", created_by=self.user)
        other_org = Organization.objects.create(name="Other")
        create_cimd_verification_token(organization=other_org, label="Theirs", created_by=None)

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["label"], "Ours")
        self.assertNotIn("value", results[0])

    def test_admin_can_revoke(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        token, _ = create_cimd_verification_token(
            organization=self.organization, label="Revocable", created_by=self.user
        )

        response = self.client.delete(self._url(str(token.id)))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CIMDVerificationToken.objects.filter(id=token.id).exists())

    def test_blank_label_rejected(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.post(self._url(), {"label": "   "}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
