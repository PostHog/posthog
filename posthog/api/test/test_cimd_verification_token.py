from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.api.oauth.cimd import _token_is_bound_to_url
from posthog.models import Organization, OrganizationMembership
from posthog.models.oauth import CIMDVerificationToken, create_cimd_verification_token, normalize_cimd_url

VALID_CIMD_URL = "https://app.example.com/.well-known/oauth-client-metadata.json"
OTHER_VALID_CIMD_URL = "https://app.example.com/.well-known/other-metadata.json"


class TestCIMDVerificationTokenViewSet(APIBaseTest):
    def _url(self, detail_id: str | None = None) -> str:
        base = f"/api/organizations/{self.organization.id}/cimd_verification_tokens/"
        return f"{base}{detail_id}/" if detail_id else base

    def test_admin_can_create_and_sees_plaintext_once(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(self._url(), {"label": "Prod partner", "cimd_url": VALID_CIMD_URL}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertTrue(body["value"].startswith("phvt_"))
        self.assertEqual(body["label"], "Prod partner")
        self.assertEqual(body["cimd_url"], VALID_CIMD_URL)
        self.assertTrue(body["mask_value"].startswith("phvt"))
        self.assertIn("...", body["mask_value"])

        token = CIMDVerificationToken.objects.get(id=body["id"])
        self.assertEqual(token.organization_id, self.organization.id)
        self.assertEqual(token.created_by_id, self.user.id)
        self.assertNotEqual(token.secure_value, body["value"])

    def test_non_admin_cannot_create(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.post(self._url(), {"label": "blocked", "cimd_url": VALID_CIMD_URL}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_returns_org_tokens_only_without_plaintext(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        create_cimd_verification_token(
            organization=self.organization, label="Ours", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        other_org = Organization.objects.create(name="Other")
        create_cimd_verification_token(organization=other_org, label="Theirs", cimd_url=VALID_CIMD_URL, created_by=None)

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
            organization=self.organization, label="Revocable", cimd_url=VALID_CIMD_URL, created_by=self.user
        )

        response = self.client.delete(self._url(str(token.id)))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CIMDVerificationToken.objects.filter(id=token.id).exists())

    @parameterized.expand(
        [
            ("blank_label", {"label": "   ", "cimd_url": VALID_CIMD_URL}),
            ("missing_url", {"label": "No URL"}),
            ("null_url", {"label": "Null URL", "cimd_url": None}),
            ("http_url", {"label": "Insecure", "cimd_url": "http://app.example.com/cimd.json"}),
            ("url_without_path", {"label": "No path", "cimd_url": "https://app.example.com"}),
            ("non_numeric_port", {"label": "Bad port", "cimd_url": "https://app.example.com:abc/cimd.json"}),
            ("out_of_range_port", {"label": "Big port", "cimd_url": "https://app.example.com:99999/cimd.json"}),
            # Passes the raw shape check (path is "//", neither "" nor "/") but normalizes to
            # no path at all, so it could never match a real fetch URL. Must be rejected at
            # issuance rather than silently accepted and never verifying.
            ("no_path_after_normalizing", {"label": "Double slash", "cimd_url": "https://app.example.com//"}),
        ]
    )
    def test_invalid_payload_rejected(self, _name, payload):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.post(self._url(), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(CIMDVerificationToken.objects.filter(organization=self.organization).exists())

    @parameterized.expand(
        [
            ("already_normalized", VALID_CIMD_URL),
            ("uppercase_host", "https://APP.Example.COM/.well-known/oauth-client-metadata.json"),
            ("explicit_default_port", "https://app.example.com:443/.well-known/oauth-client-metadata.json"),
            ("trailing_slash", VALID_CIMD_URL + "/"),
        ]
    )
    def test_patch_binds_unbound_token_to_normalized_value_and_it_then_verifies(self, _name, raw_url):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        token, _ = create_cimd_verification_token(
            organization=self.organization, label="Legacy", cimd_url=VALID_CIMD_URL, created_by=self.user
        )
        token.cimd_url = None
        token.save(update_fields=["cimd_url"])

        response = self.client.patch(self._url(str(token.id)), {"cimd_url": raw_url}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["cimd_url"], VALID_CIMD_URL)
        token.refresh_from_db()
        # Asserting the stored column, not just the response body or the status code: the
        # ModelSerializer update path writes validated_data straight to the column, so a
        # PATCH that validated a raw spelling but returned it unnormalized would still 200
        # while storing a value that could never match a real fetch's normalized URL.
        self.assertEqual(token.cimd_url, VALID_CIMD_URL)
        self.assertTrue(_token_is_bound_to_url(token, VALID_CIMD_URL))

    def test_patch_on_already_bound_token_is_rejected_and_leaves_value_unchanged(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        token, _ = create_cimd_verification_token(
            organization=self.organization, label="Bound", cimd_url=VALID_CIMD_URL, created_by=self.user
        )

        response = self.client.patch(self._url(str(token.id)), {"cimd_url": OTHER_VALID_CIMD_URL}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        token.refresh_from_db()
        self.assertEqual(token.cimd_url, normalize_cimd_url(VALID_CIMD_URL))

    def test_patch_is_org_scoped(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        other_org = Organization.objects.create(name="Other")
        other_token, _ = create_cimd_verification_token(
            organization=other_org, label="Theirs", cimd_url=VALID_CIMD_URL, created_by=None
        )
        other_token.cimd_url = None
        other_token.save(update_fields=["cimd_url"])

        response = self.client.patch(self._url(str(other_token.id)), {"cimd_url": VALID_CIMD_URL}, format="json")

        self.assertIn(response.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN))
        other_token.refresh_from_db()
        self.assertIsNone(other_token.cimd_url)
