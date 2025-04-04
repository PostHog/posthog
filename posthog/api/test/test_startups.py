from rest_framework import status
from datetime import timedelta
from django.utils import timezone
from unittest.mock import patch, MagicMock
from rest_framework.exceptions import ValidationError

from posthog.test.base import APIBaseTest
from posthog.models.organization import Organization, OrganizationMembership
from posthog.api.startups import check_organization_eligibility


class TestOrganizationEligibility(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Organization")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            level=OrganizationMembership.Level.ADMIN,
        )

        # Create an organization where the user is not an admin
        self.non_admin_org = Organization.objects.create(name="Non-Admin Organization")
        OrganizationMembership.objects.create(
            organization=self.non_admin_org,
            user=self.user,
            level=OrganizationMembership.Level.MEMBER,
        )

    def test_nonexistent_organization(self):
        """Test that a nonexistent organization ID raises the correct error."""
        with self.assertRaises(ValidationError) as context:
            check_organization_eligibility("00000000-0000-0000-0000-000000000000", self.user)

        self.assertEqual(str(context.exception.detail[0]), "Organization not found")

    def test_non_admin_user(self):
        """Test that a non-admin user cannot apply for the startup program."""
        with self.assertRaises(ValidationError) as context:
            check_organization_eligibility(str(self.non_admin_org.id), self.user)

        self.assertEqual(str(context.exception.detail[0]), "You must be an organization admin or owner to apply")

    @patch("posthog.api.startups.get_cached_instance_license")
    def test_no_license(self, mock_get_license):
        """Test that a missing license raises the correct error."""
        mock_get_license.return_value = None

        with self.assertRaises(ValidationError) as context:
            check_organization_eligibility(str(self.organization.id), self.user)

        self.assertEqual(str(context.exception.detail[0]), "No license found")

    @patch("posthog.api.startups.get_cached_instance_license")
    @patch("ee.billing.billing_manager.BillingManager.get_billing")
    def test_no_active_subscription(self, mock_get_billing, mock_get_license):
        """Test that an organization without an active subscription cannot apply."""
        mock_get_license.return_value = MagicMock()
        mock_get_billing.return_value = {"has_active_subscription": False}

        with self.assertRaises(ValidationError) as context:
            check_organization_eligibility(str(self.organization.id), self.user)

        self.assertEqual(
            str(context.exception.detail[0]), "You need an active subscription to apply for the startup program"
        )

    @patch("posthog.api.startups.get_cached_instance_license")
    @patch("ee.billing.billing_manager.BillingManager.get_billing")
    def test_already_in_startup_program(self, mock_get_billing, mock_get_license):
        """Test that an organization already in the startup program cannot apply again."""
        mock_get_license.return_value = MagicMock()
        mock_get_billing.return_value = {"has_active_subscription": True, "startup_program_label": "startups"}

        with self.assertRaises(ValidationError) as context:
            check_organization_eligibility(str(self.organization.id), self.user)

        self.assertEqual(str(context.exception.detail[0]), "Your organization is already in the startup program")

    @patch("posthog.api.startups.get_cached_instance_license")
    @patch("ee.billing.billing_manager.BillingManager.get_billing")
    def test_valid_organization(self, mock_get_billing, mock_get_license):
        """Test that a valid organization can apply for the startup program."""
        mock_get_license.return_value = MagicMock()
        mock_get_billing.return_value = {"has_active_subscription": True, "startup_program_label": None}

        result = check_organization_eligibility(str(self.organization.id), self.user)

        self.assertEqual(result, str(self.organization.id))
        mock_get_billing.assert_called_once()

    @patch("posthog.api.startups.get_cached_instance_license")
    @patch("ee.billing.billing_manager.BillingManager.get_billing")
    def test_billing_without_startup_program_field(self, mock_get_billing, mock_get_license):
        """Test that billing response without startup_program_label field works."""
        mock_get_license.return_value = MagicMock()
        mock_get_billing.return_value = {
            "has_active_subscription": True,
            # startup_program_label is missing
        }

        result = check_organization_eligibility(str(self.organization.id), self.user)

        self.assertEqual(result, str(self.organization.id))
        mock_get_billing.assert_called_once()

    @patch("posthog.api.startups.get_cached_instance_license")
    @patch("ee.billing.billing_manager.BillingManager.get_billing")
    def test_empty_startup_program_label(self, mock_get_billing, mock_get_license):
        """Test that an empty startup_program_label is treated as not being in the program."""
        mock_get_license.return_value = MagicMock()
        mock_get_billing.return_value = {"has_active_subscription": True, "startup_program_label": ""}

        result = check_organization_eligibility(str(self.organization.id), self.user)

        self.assertEqual(result, str(self.organization.id))
        mock_get_billing.assert_called_once()


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

    @patch("posthog.api.startups.check_organization_eligibility")
    def test_missing_startups_fields(self, mock_check_eligibility):
        """Test that startup program applications require the appropriate fields."""
        mock_check_eligibility.return_value = str(self.organization.id)

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

    @patch("posthog.api.startups.check_organization_eligibility")
    def test_missing_yc_fields(self, mock_check_eligibility):
        """Test that YC program applications require the appropriate fields."""
        mock_check_eligibility.return_value = str(self.organization.id)

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

    @patch("posthog.api.startups.check_organization_eligibility")
    def test_startup_older_than_two_years_rejected(self, mock_check_eligibility):
        """Test that startups older than 2 years are rejected."""
        # Calculate a date that's just over 2 years old
        old_date = (timezone.now().date() - timedelta(days=732)).strftime("%Y-%m-%d")  # 2 years and 2 days ago
        mock_check_eligibility.return_value = str(self.organization.id)

        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "startups",
                "organization_id": str(self.organization.id),
                "raised": "1000000",
                "incorporation_date": old_date,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(response_data["attr"], "incorporation_date")
        self.assertEqual(
            response_data["detail"], "Companies older than 2 years are not eligible for the startup program"
        )

    @patch("posthog.api.startups.check_organization_eligibility")
    def test_startup_raised_too_much_rejected(self, mock_check_eligibility):
        """Test that startups that have raised $5M or more are rejected."""
        mock_check_eligibility.return_value = str(self.organization.id)

        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "startups",
                "organization_id": str(self.organization.id),
                "raised": "5000000",  # $5M
                "incorporation_date": "2023-01-01",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(response_data["attr"], "raised")
        self.assertEqual(
            response_data["detail"], "Companies that have raised $5M or more are not eligible for the startup program"
        )

    @patch("posthog.api.startups.check_organization_eligibility")
    @patch("posthog.api.startups.StartupApplicationSerializer.create")
    def test_successful_startup_application(self, mock_create, mock_check_eligibility):
        """Test that a valid startup application is successfully submitted."""
        one_year_ago = (timezone.now().date() - timedelta(days=365)).strftime("%Y-%m-%d")
        mock_check_eligibility.return_value = str(self.organization.id)

        mock_create.return_value = {
            "organization_id": str(self.organization.id),
            "organization_name": "Test Organization",
            "program": "startups",
            "raised": "1000000",
            "incorporation_date": one_year_ago,
            "email": self.user.email,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
        }

        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "startups",
                "organization_id": str(self.organization.id),
                "raised": "1000000",  # $1M
                "incorporation_date": one_year_ago,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["organization_id"], str(self.organization.id))
        self.assertEqual(response_data["program"], "startups")
        self.assertEqual(response_data["raised"], "1000000")
        self.assertEqual(response_data["incorporation_date"], one_year_ago)

    @patch("posthog.api.startups.check_organization_eligibility")
    @patch("posthog.api.startups.StartupApplicationSerializer.create")
    def test_successful_yc_application(self, mock_create, mock_check_eligibility):
        """Test that a valid YC application is successfully submitted."""
        mock_check_eligibility.return_value = str(self.organization.id)

        mock_create.return_value = {
            "organization_id": str(self.organization.id),
            "organization_name": "Test Organization",
            "program": "yc",
            "yc_batch": "W24",
            "yc_proof_screenshot_url": "https://example.com/screenshot.jpg",
            "yc_merch_count": 3,
            "email": self.user.email,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
        }

        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "yc",
                "organization_id": str(self.organization.id),
                "yc_batch": "W24",
                "yc_proof_screenshot_url": "https://example.com/screenshot.jpg",
                "yc_merch_count": 3,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["organization_id"], str(self.organization.id))
        self.assertEqual(response_data["program"], "yc")
        self.assertEqual(response_data["yc_batch"], "W24")
        self.assertEqual(response_data["yc_proof_screenshot_url"], "https://example.com/screenshot.jpg")
        self.assertEqual(response_data["yc_merch_count"], 3)
