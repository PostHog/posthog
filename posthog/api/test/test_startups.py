from rest_framework import status
from datetime import timedelta
from django.utils import timezone
from unittest.mock import patch, MagicMock
from rest_framework.exceptions import ValidationError

from posthog.test.base import APIBaseTest
from posthog.models.organization import Organization, OrganizationMembership
from posthog.api.startups import (
    check_organization_eligibility,
    verify_yc_batch_membership,
    extract_domain_from_url,
    get_sorted_yc_batches,
    get_yc_deal_type,
)


class TestYCBatchVerification(APIBaseTest):
    def test_extract_domain(self):
        """Test the domain extraction function."""
        self.assertEqual(extract_domain_from_url("https://www.example.com"), "example.com")
        self.assertEqual(extract_domain_from_url("http://example.com"), "example.com")
        self.assertEqual(extract_domain_from_url("example.com"), "example.com")
        self.assertEqual(extract_domain_from_url("www.example.com"), "example.com")
        self.assertEqual(extract_domain_from_url("https://example.com/path?query=value"), "example.com")

    @patch("requests.get")
    def test_verify_yc_batch_membership_success(self, mock_get):
        """Test successful YC batch verification."""
        # Create a mock response with a company that matches
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = [
            {"name": "Test Company", "website": "https://testcompany.com"},
            {"name": "Another Company", "website": "https://anothercompany.com"},
        ]
        mock_get.return_value = mock_response

        # Test matching by name
        self.assertTrue(verify_yc_batch_membership("W23", "Test Company", "user@blabla.com"))

        # Test matching by domain
        self.assertTrue(verify_yc_batch_membership("W23", "Different Name", "user@testcompany.com"))

        # Test public domain is skipped and name is used instead
        self.assertTrue(verify_yc_batch_membership("W23", "Test Company", "user@gmail.com"))

    @patch("requests.get")
    def test_verify_yc_batch_membership_failure(self, mock_get):
        """Test failed YC batch verification."""
        # Create a mock response with companies that don't match
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = [
            {"name": "Test Company", "website": "https://testcompany.com"},
            {"name": "Another Company", "website": "https://anothercompany.com"},
        ]
        mock_get.return_value = mock_response

        # Test non-matching company
        self.assertFalse(verify_yc_batch_membership("W23", "Unknown Company", "user@unknown.com"))

    @patch("requests.get")
    def test_verify_yc_batch_earlier_batches(self, mock_get):
        """Test handling of 'Earlier' batches which can't be verified."""
        self.assertFalse(verify_yc_batch_membership("Earlier", "Any Company", "user@unknown.com"))
        mock_get.assert_not_called()

    @patch("requests.get")
    def test_verify_yc_batch_api_error(self, mock_get):
        """Test handling of API errors."""
        # Mock a failed API response
        mock_response = MagicMock()
        mock_response.ok = False
        mock_get.return_value = mock_response

        # Should return False (not verified) instead of raising an exception
        self.assertFalse(verify_yc_batch_membership("W23", "Test Company", "user@blabla.com"))

    @patch("requests.get")
    def test_verify_yc_batch_exception(self, mock_get):
        """Test handling of exceptions during verification."""
        # Mock an exception during the API call
        mock_get.side_effect = Exception("Network error")

        # Should handle the exception and return False
        self.assertFalse(verify_yc_batch_membership("W23", "Test Company", "user@blabla.com"))


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
                "program": "startup",
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
                "program": "startup",
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
                "program": "startup",
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
                "program": "startup",
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
                "program": "startup",
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
                "program": "YC",
                "organization_id": str(self.organization.id),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(response_data["detail"], "YC batch is required for YC applications")

    @patch("posthog.api.startups.check_organization_eligibility")
    def test_startup_older_than_two_years_rejected(self, mock_check_eligibility):
        """Test that startups older than 2 years are rejected."""
        # Calculate a date that's just over 2 years old
        old_date = (timezone.now().date() - timedelta(days=732)).strftime("%Y-%m-%d")  # 2 years and 2 days ago
        mock_check_eligibility.return_value = str(self.organization.id)

        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "startup",
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
                "program": "startup",
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
    @patch("posthog.api.startups.verify_yc_batch_membership")
    @patch("posthog.api.startups.StartupApplicationSerializer.create")
    def test_successful_startup_application(self, mock_create, mock_verify, mock_check_eligibility):
        """Test that a valid startup application is successfully submitted."""
        one_year_ago = (timezone.now().date() - timedelta(days=365)).strftime("%Y-%m-%d")
        mock_check_eligibility.return_value = str(self.organization.id)

        mock_create.return_value = {
            "organization_id": str(self.organization.id),
            "organization_name": "Test Organization",
            "program": "startup",
            "raised": "1000000",
            "incorporation_date": one_year_ago,
            "email": self.user.email,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
        }

        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "startup",
                "organization_id": str(self.organization.id),
                "raised": "1000000",  # $1M
                "incorporation_date": one_year_ago,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["organization_id"], str(self.organization.id))
        self.assertEqual(response_data["program"], "startup")
        self.assertEqual(response_data["raised"], "1000000")
        self.assertEqual(response_data["incorporation_date"], one_year_ago)

    @patch("posthog.api.startups.check_organization_eligibility")
    @patch("posthog.api.startups.verify_yc_batch_membership")
    @patch("posthog.api.startups.StartupApplicationSerializer.create")
    def test_successful_yc_application(self, mock_create, mock_verify, mock_check_eligibility):
        """Test that a valid YC application is successfully submitted with screenshot."""
        mock_check_eligibility.return_value = str(self.organization.id)
        mock_verify.return_value = False  # YC batch verification fails, requiring screenshot

        mock_create.return_value = {
            "organization_id": str(self.organization.id),
            "organization_name": "Test Organization",
            "program": "YC",
            "yc_batch": "W24",
            "yc_verified": False,
            "yc_proof_screenshot_url": "https://example.com/screenshot.jpg",
            "yc_merch_count": 3,
            "email": self.user.email,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
        }

        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "YC",
                "organization_id": str(self.organization.id),
                "yc_batch": "W24",
                "yc_proof_screenshot_url": "https://example.com/screenshot.jpg",
                "yc_merch_count": 3,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["organization_id"], str(self.organization.id))
        self.assertEqual(response_data["program"], "YC")
        self.assertEqual(response_data["yc_batch"], "W24")
        self.assertEqual(response_data["yc_proof_screenshot_url"], "https://example.com/screenshot.jpg")
        self.assertEqual(response_data["yc_merch_count"], 3)

    @patch("posthog.api.startups.check_organization_eligibility")
    @patch("posthog.api.startups.verify_yc_batch_membership")
    @patch("posthog.api.startups.StartupApplicationSerializer.create")
    def test_yc_application_with_verified_batch(self, mock_create, mock_verify, mock_check_eligibility):
        """Test that a YC application with a verified batch doesn't require a screenshot."""
        mock_check_eligibility.return_value = str(self.organization.id)
        mock_verify.return_value = True  # YC batch verification succeeds

        mock_create.return_value = {
            "organization_id": str(self.organization.id),
            "organization_name": "Test Organization",
            "program": "YC",
            "yc_batch": "W24",
            "yc_verified": True,
            "email": self.user.email,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
        }

        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "YC",
                "organization_id": str(self.organization.id),
                "yc_batch": "W24",
                # Note: No screenshot URL is provided since verification succeeds
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["organization_id"], str(self.organization.id))
        self.assertEqual(response_data["program"], "YC")
        self.assertEqual(response_data["yc_batch"], "W24")
        self.assertTrue(response_data["yc_verified"])

    @patch("posthog.api.startups.check_organization_eligibility")
    @patch("posthog.api.startups.verify_yc_batch_membership")
    def test_yc_application_with_unverified_batch_requires_screenshot(self, mock_verify, mock_check_eligibility):
        """Test that a YC application with an unverified batch requires a screenshot."""
        mock_check_eligibility.return_value = str(self.organization.id)
        mock_verify.return_value = False  # YC batch verification fails

        response = self.client.post(
            "/api/startups/apply/",
            {
                "program": "YC",
                "organization_id": str(self.organization.id),
                "yc_batch": "W24",
                # No screenshot URL is provided, which should cause validation to fail
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["type"], "validation_error")
        self.assertEqual(
            response_data["detail"],
            "Screenshot proof is required for YC applications that cannot be automatically verified",
        )


class TestYCBatchSorting(APIBaseTest):
    @patch("requests.get")
    def test_batch_sorting(self, mock_get):
        """Test that batches are sorted correctly by year and season."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "batches": {
                "x25": {"name": "X25"},
                "w25": {"name": "W25"},
                "f24": {"name": "F24"},
                "s24": {"name": "S24"},
                "w24": {"name": "W24"},
                "s06": {"name": "S06"},
                "w06": {"name": "W06"},
                "s05": {"name": "S05"},
                "ik12": {"name": "IK12"},
                "unspecified": {"name": "Unspecified"},
            }
        }
        mock_get.return_value = mock_response

        sorted_batches = get_sorted_yc_batches()
        expected_order = [
            "X25",  # Most recent first
            "W25",
            "F24",  # Fall before Summer
            "S24",  # Summer before Winter
            "W24",
            "S06",
            "W06",  # Old batches at the end
            "S05",
            "IK12",
            "UNSPECIFIED",
        ]

        self.assertEqual(sorted_batches, expected_order)

    @patch("requests.get")
    def test_deal_type_categorization(self, mock_get):
        """Test that batches are correctly categorized into deal types."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "batches": {
                "x25": {"name": "X25"},
                "w25": {"name": "W25"},
                "f24": {"name": "F24"},
                "s24": {"name": "S24"},
                "w24": {"name": "W24"},
                "f23": {"name": "F23"},
                "s23": {"name": "S23"},
                "w23": {"name": "W23"},
                "w06": {"name": "W06"},
            }
        }
        mock_get.return_value = mock_response

        # Test current batches (first two)
        self.assertEqual(get_yc_deal_type("X25"), "current")
        self.assertEqual(get_yc_deal_type("W25"), "current")
        self.assertEqual(get_yc_deal_type("x25"), "current")  # Case insensitive

        # Test old batches (next four)
        self.assertEqual(get_yc_deal_type("F24"), "old")
        self.assertEqual(get_yc_deal_type("S24"), "old")
        self.assertEqual(get_yc_deal_type("W24"), "old")
        self.assertEqual(get_yc_deal_type("F23"), "old")

        # Test older batches
        self.assertEqual(get_yc_deal_type("S23"), "older")
        self.assertEqual(get_yc_deal_type("W23"), "older")
        self.assertEqual(get_yc_deal_type("W06"), "older")

        # Test invalid/unknown batches
        self.assertEqual(get_yc_deal_type("INVALID"), "older")
        self.assertEqual(get_yc_deal_type("IK12"), "older")
        self.assertEqual(get_yc_deal_type(""), "older")
