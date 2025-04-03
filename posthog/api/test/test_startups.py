from rest_framework import status

from posthog.test.base import APIBaseTest
from posthog.models.organization import Organization, OrganizationMembership


class TestStartupsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Organization")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            level=OrganizationMembership.Level.ADMIN,
        )

    def test_unauthenticated_request_rejected(self):
        """Test that unauthenticated requests are rejected."""
        self.client.logout()
        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "startups",
                "organization_id": str(self.organization.id),
                "raised": "1000000",
                "incorporation_date": "2023-01-01",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_no_organization_id_rejected(self):
        """Test that requests without organization_id are rejected."""
        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "startups",
                "raised": "1000000",
                "incorporation_date": "2023-01-01",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(response_data["code"], "required")
        self.assertEqual(response_data["attr"], "organization_id")

    def test_non_admin_user_rejected(self):
        """Test that non-admin users are rejected."""
        # Create a new organization where the user is not an admin
        org2 = Organization.objects.create(name="Another Organization")
        OrganizationMembership.objects.create(
            organization=org2,
            user=self.user,
            level=OrganizationMembership.Level.MEMBER,
        )

        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "startups",
                "organization_id": str(org2.id),
                "raised": "1000000",
                "incorporation_date": "2023-01-01",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(response_data["code"], "invalid_input")
        self.assertEqual(response_data["attr"], "organization_id")
        self.assertEqual(response_data["detail"], "You must be an organization admin or owner to apply")

    def test_missing_startups_fields(self):
        """Test that startup program applications require the appropriate fields."""
        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "startups",
                "organization_id": str(self.organization.id),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(response_data["detail"], "Funding amount is required for startup program applications")

        # Test missing incorporation date
        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "startups",
                "organization_id": str(self.organization.id),
                "raised": "1000000",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(response_data["detail"], "Incorporation date is required for startup program applications")

    def test_missing_yc_fields(self):
        """Test that YC program applications require the appropriate fields."""
        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "yc",
                "organization_id": str(self.organization.id),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(response_data["detail"], "YC batch is required for YC applications")

        # Test missing screenshot proof
        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "yc",
                "organization_id": str(self.organization.id),
                "yc_batch": "W23",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(response_data["detail"], "Screenshot proof is required for YC applications")
