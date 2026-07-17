import json

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from rest_framework import status

from posthog.models import User

from products.conversations.backend.cross_region import (
    CROSS_REGION_SIGNATURE_HEADER,
    CROSS_REGION_TIMESTAMP_HEADER,
    OrgIdentity,
    sign_request,
    verify_org_memberships,
    verify_org_memberships_cross_region,
)

INTERNAL_ENDPOINT = "/api/conversations/internal/verify_org_memberships/"
CROSS_REGION_SECRET = "test-conversations-cross-region-secret"


class TestVerifyOrgMemberships(BaseTest):
    def setUp(self):
        super().setUp()
        self.member = User.objects.create_and_join(self.organization, "member@example.com", None, "Member")
        self.member.distinct_id = "member-distinct-id"
        self.member.save()
        self.org_id = str(self.organization.id)

    @parameterized.expand(
        [
            ("distinct_id_match", "member-distinct-id", "", True),
            ("email_equals_distinct_id", "member@example.com", "", True),
            ("email_equals_email_from", "", "member@example.com", True),
            ("email_from_case_insensitive", "", "MEMBER@EXAMPLE.COM", True),
            ("no_match", "stranger", "stranger@example.com", False),
        ]
    )
    def test_matches_membership_identity(self, _name, distinct_id, email_from, expected):
        identity = OrgIdentity(organization_id=self.org_id, distinct_id=distinct_id, email_from=email_from)
        assert (identity in verify_org_memberships([identity])) is expected

    def test_membership_in_a_different_org_does_not_verify(self):
        identity = OrgIdentity(
            organization_id="019b2be2-5563-0000-6408-1e45bbe55e38",  # a member, but not of this org
            distinct_id="member-distinct-id",
            email_from="",
        )
        assert verify_org_memberships([identity]) == set()


@override_settings(CONVERSATIONS_CROSS_REGION_SECRET=CROSS_REGION_SECRET)
class TestCrossRegionOrgVerificationEndpoint(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.member = User.objects.create_and_join(self.organization, "member@example.com", None, "Member")
        self.member.distinct_id = "member-distinct-id"
        self.member.save()
        self.org_id = str(self.organization.id)
        self.client.logout()  # the endpoint authenticates purely off the signature

    def _post(self, body: bytes, headers: dict[str, str] | None = None):
        return self.client.post(INTERNAL_ENDPOINT, data=body, content_type="application/json", headers=headers or {})

    def test_unsigned_request_rejected(self):
        body = json.dumps({"identities": []}).encode("utf-8")
        assert self._post(body).status_code == status.HTTP_401_UNAUTHORIZED

    def test_tampered_body_rejected(self):
        body = json.dumps(
            {"identities": [{"organization_id": self.org_id, "distinct_id": "member-distinct-id"}]}
        ).encode("utf-8")
        signature, ts = sign_request(body, CROSS_REGION_SECRET)
        headers = {CROSS_REGION_SIGNATURE_HEADER: signature, CROSS_REGION_TIMESTAMP_HEADER: ts}
        tampered = json.dumps({"identities": [{"organization_id": self.org_id, "distinct_id": "attacker"}]}).encode(
            "utf-8"
        )
        assert self._post(tampered, headers).status_code == status.HTTP_401_UNAUTHORIZED

    def test_signed_request_returns_indices_of_verified_members(self):
        payload = {
            "identities": [
                {"organization_id": self.org_id, "distinct_id": "member-distinct-id", "email_from": ""},
                {"organization_id": self.org_id, "distinct_id": "stranger", "email_from": "stranger@example.com"},
            ]
        }
        body = json.dumps(payload).encode("utf-8")
        signature, ts = sign_request(body, CROSS_REGION_SECRET)
        headers = {CROSS_REGION_SIGNATURE_HEADER: signature, CROSS_REGION_TIMESTAMP_HEADER: ts}

        response = self._post(body, headers)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"verified_indices": [0]}


class TestVerifyOrgMembershipsCrossRegionClient(SimpleTestCase):
    def setUp(self):
        self.identities = [OrgIdentity("org-1", "did-1", ""), OrgIdentity("org-2", "did-2", "")]

    @parameterized.expand(
        [
            ("region_not_cloud", "DEV", CROSS_REGION_SECRET),
            ("secret_unset", "US", ""),
        ]
    )
    def test_no_probe_when_disabled(self, _name, cloud_deployment, secret):
        with override_settings(CLOUD_DEPLOYMENT=cloud_deployment, CONVERSATIONS_CROSS_REGION_SECRET=secret):
            with patch("products.conversations.backend.cross_region.requests.post") as post:
                assert verify_org_memberships_cross_region(self.identities) == set()
        post.assert_not_called()

    @override_settings(CLOUD_DEPLOYMENT="US", CONVERSATIONS_CROSS_REGION_SECRET=CROSS_REGION_SECRET)
    def test_transport_error_returns_empty(self):
        with patch(
            "products.conversations.backend.cross_region.requests.post",
            side_effect=requests.RequestException("boom"),
        ):
            assert verify_org_memberships_cross_region(self.identities) == set()

    @override_settings(CLOUD_DEPLOYMENT="US", CONVERSATIONS_CROSS_REGION_SECRET=CROSS_REGION_SECRET)
    def test_non_200_returns_empty(self):
        response = MagicMock(status_code=500)
        with patch("products.conversations.backend.cross_region.requests.post", return_value=response):
            assert verify_org_memberships_cross_region(self.identities) == set()

    @override_settings(CLOUD_DEPLOYMENT="US", CONVERSATIONS_CROSS_REGION_SECRET=CROSS_REGION_SECRET)
    def test_success_maps_indices_back_to_identities(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"verified_indices": [1]}
        with patch("products.conversations.backend.cross_region.requests.post", return_value=response):
            assert verify_org_memberships_cross_region(self.identities) == {self.identities[1]}
