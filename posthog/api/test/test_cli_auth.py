from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.utils import timezone

from rest_framework import status

from posthog.api.cli_auth import CLI_SCOPES, DEVICE_CODE_EXPIRY_SECONDS, get_device_cache_key, get_user_code_cache_key
from posthog.models import PersonalAPIKey, Team, User
from posthog.models.organization import Organization
from posthog.models.personal_api_key import hash_key_value


class TestCLIAuthDeviceCodeEndpoint(APIBaseTest):
    """
    Tests for the device code request endpoint (step 1 of OAuth device flow)
    """

    def setUp(self):
        super().setUp()
        cache.clear()  # Clear cache before each test

    def test_device_code_request_returns_correct_data(self):
        """Test that requesting a device code returns all required fields"""
        response = self.client.post("/api/cli-auth/device-code/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Check all required fields are present
        self.assertIn("device_code", data)
        self.assertIn("user_code", data)
        self.assertIn("verification_uri", data)
        self.assertIn("verification_uri_complete", data)
        self.assertIn("expires_in", data)
        self.assertIn("interval", data)

        # Check values are correct
        self.assertEqual(data["expires_in"], DEVICE_CODE_EXPIRY_SECONDS)
        self.assertIn("/cli/authorize", data["verification_uri"])
        self.assertIn(data["user_code"], data["verification_uri_complete"])

        # Verify user code format (XXXX-XXXX)
        user_code = data["user_code"]
        self.assertEqual(len(user_code), 9)
        self.assertEqual(user_code[4], "-")
        self.assertTrue(user_code[:4].isalpha())
        self.assertTrue(user_code[5:].isdigit())

    def test_device_code_is_stored_in_cache(self):
        """Test that device code and user code are properly stored in cache"""
        response = self.client.post("/api/cli-auth/device-code/")
        data = response.json()

        device_code = data["device_code"]
        user_code = data["user_code"]

        # Check device code is in cache
        device_cache_key = get_device_cache_key(device_code)
        device_data = cache.get(device_cache_key)
        self.assertIsNotNone(device_data)
        self.assertEqual(device_data["user_code"], user_code)
        self.assertEqual(device_data["status"], "pending")

        # Check user code reverse lookup is in cache
        user_code_cache_key = get_user_code_cache_key(user_code)
        cached_device_code = cache.get(user_code_cache_key)
        self.assertEqual(cached_device_code, device_code)

    def test_device_code_works_without_authentication(self):
        """Test that device code endpoint works for unauthenticated requests"""
        self.client.logout()
        response = self.client.post("/api/cli-auth/device-code/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestCLIAuthAuthorizeEndpoint(APIBaseTest):
    """
    Tests for the authorization endpoint (step 2 of OAuth device flow)
    """

    def setUp(self):
        super().setUp()
        cache.clear()

        # Create a device code for testing
        response = self.client.post("/api/cli-auth/device-code/")
        self.device_data = response.json()
        self.device_code = self.device_data["device_code"]
        self.user_code = self.device_data["user_code"]

    def test_successful_authorization_creates_api_key(self):
        """Test that successful authorization creates a Personal API Key"""
        initial_key_count = PersonalAPIKey.objects.filter(user=self.user).count()

        response = self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": self.user_code, "project_id": self.team.id},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("label", data)
        self.assertIn("mask_value", data)

        # Check that API key was created
        new_key_count = PersonalAPIKey.objects.filter(user=self.user).count()
        self.assertEqual(new_key_count, initial_key_count + 1)

        # Check the created key has correct scopes
        api_key = PersonalAPIKey.objects.filter(user=self.user).order_by("-created_at").first()
        assert api_key is not None
        self.assertEqual(api_key.scopes, CLI_SCOPES)
        self.assertIn("CLI -", api_key.label)

    def test_authorization_requires_authentication(self):
        """Test that authorization endpoint requires user to be logged in"""
        self.client.logout()

        response = self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": self.user_code, "project_id": self.team.id},
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authorization_rejects_invalid_user_code(self):
        """Test that authorization fails with invalid user code"""
        response = self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": "XXXX-9999", "project_id": self.team.id},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn("error", data)
        self.assertEqual(data["error"], "invalid_code")

    def test_authorization_rejects_expired_user_code(self):
        """Test that authorization fails with expired user code"""
        # Wait for the code to expire
        with freeze_time(timezone.now() + timedelta(seconds=DEVICE_CODE_EXPIRY_SECONDS + 1)):
            response = self.client.post(
                "/api/cli-auth/authorize/",
                {"user_code": self.user_code, "project_id": self.team.id},
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_code")

    def test_authorization_rejects_user_without_team_access(self):
        """Test that user cannot authorize for a team they don't have access to"""
        # Create another organization and team
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        response = self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": self.user_code, "project_id": other_team.id},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["error"], "access_denied")

        # Verify no API key was created
        api_keys = PersonalAPIKey.objects.filter(user=self.user).count()
        self.assertEqual(api_keys, 0)

    def test_authorization_rejects_nonexistent_project(self):
        """Test that authorization fails with non-existent project ID"""
        response = self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": self.user_code, "project_id": 99999},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_project")

    def test_authorization_updates_cache_with_api_key(self):
        """Test that authorization updates the cache with the API key"""
        response = self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": self.user_code, "project_id": self.team.id},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check cache was updated
        device_cache_key = get_device_cache_key(self.device_code)
        device_data = cache.get(device_cache_key)

        self.assertEqual(device_data["status"], "authorized")
        self.assertIn("personal_api_key", device_data)
        self.assertEqual(device_data["project_id"], str(self.team.id))
        self.assertEqual(device_data["user_id"], self.user.id)

    def test_multiple_users_can_authorize_different_codes(self):
        """Test that multiple users can authorize different device codes concurrently"""
        # Create another user
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password123")

        # Create device code for other user
        response2 = self.client.post("/api/cli-auth/device-code/")
        user_code2 = response2.json()["user_code"]

        # First user authorizes their code
        response = self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": self.user_code, "project_id": self.team.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Switch to other user
        self.client.force_login(other_user)

        # Other user authorizes their code
        response = self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": user_code2, "project_id": self.team.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Both users should have their own API keys
        self.assertEqual(PersonalAPIKey.objects.filter(user=self.user).count(), 1)
        self.assertEqual(PersonalAPIKey.objects.filter(user=other_user).count(), 1)


class TestCLIAuthPollEndpoint(APIBaseTest):
    """
    Tests for the poll endpoint (step 3 of OAuth device flow)
    """

    def setUp(self):
        super().setUp()
        cache.clear()

        # Create and authorize a device code
        response = self.client.post("/api/cli-auth/device-code/")
        self.device_data = response.json()
        self.device_code = self.device_data["device_code"]
        self.user_code = self.device_data["user_code"]

    def test_poll_returns_pending_before_authorization(self):
        """Test that polling returns pending status before user authorizes"""
        response = self.client.post("/api/cli-auth/poll/", {"device_code": self.device_code})

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        data = response.json()
        self.assertEqual(data["status"], "pending")

    def test_poll_returns_api_key_after_authorization(self):
        """Test that polling returns API key after user authorizes"""
        # Authorize the code
        self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": self.user_code, "project_id": self.team.id},
        )

        # Poll for the result
        response = self.client.post("/api/cli-auth/poll/", {"device_code": self.device_code})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], "authorized")
        self.assertIn("personal_api_key", data)
        self.assertIn("label", data)
        self.assertEqual(data["project_id"], str(self.team.id))

        # Verify the API key is valid
        api_key = data["personal_api_key"]
        self.assertTrue(api_key.startswith("phx_"))

    def test_poll_returns_expired_for_old_code(self):
        """Test that polling returns expired for old device codes"""
        with freeze_time(timezone.now() + timedelta(seconds=DEVICE_CODE_EXPIRY_SECONDS + 1)):
            response = self.client.post("/api/cli-auth/poll/", {"device_code": self.device_code})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["status"], "expired")

    def test_poll_returns_expired_for_nonexistent_code(self):
        """Test that polling returns expired for non-existent device codes"""
        response = self.client.post("/api/cli-auth/poll/", {"device_code": "nonexistent_code"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["status"], "expired")

    def test_poll_cleans_up_cache_after_successful_retrieval(self):
        """Test that cache is cleaned up after API key is retrieved"""
        # Authorize the code
        self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": self.user_code, "project_id": self.team.id},
        )

        # Poll for the result
        self.client.post("/api/cli-auth/poll/", {"device_code": self.device_code})

        # Verify cache is cleaned up
        device_cache_key = get_device_cache_key(self.device_code)
        user_code_cache_key = get_user_code_cache_key(self.user_code)

        self.assertIsNone(cache.get(device_cache_key))
        self.assertIsNone(cache.get(user_code_cache_key))

    def test_poll_can_be_called_multiple_times_before_authorization(self):
        """Test that poll can be called multiple times while pending"""
        # Poll multiple times
        for _ in range(3):
            response = self.client.post("/api/cli-auth/poll/", {"device_code": self.device_code})
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            self.assertEqual(response.json()["status"], "pending")

    def test_poll_works_without_authentication(self):
        """Test that poll endpoint works for unauthenticated requests"""
        self.client.logout()
        response = self.client.post("/api/cli-auth/poll/", {"device_code": self.device_code})
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    def test_poll_returns_api_key_only_once(self):
        """Test that API key can only be retrieved once"""
        # Authorize the code
        self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": self.user_code, "project_id": self.team.id},
        )

        # First poll succeeds
        response1 = self.client.post("/api/cli-auth/poll/", {"device_code": self.device_code})
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        # Second poll fails (cache cleaned up)
        response2 = self.client.post("/api/cli-auth/poll/", {"device_code": self.device_code})
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response2.json()["status"], "expired")


class TestCLIAuthEndToEnd(APIBaseTest):
    """
    End-to-end tests for the complete CLI authentication flow
    """

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_complete_authentication_flow(self):
        """Test the complete device flow from start to finish"""
        # Step 1: Request device code (CLI)
        response = self.client.post("/api/cli-auth/device-code/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        device_data = response.json()
        device_code = device_data["device_code"]
        user_code = device_data["user_code"]

        # Step 2: User opens browser and authorizes
        response = self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": user_code, "project_id": self.team.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Step 3: CLI polls and gets API key
        response = self.client.post("/api/cli-auth/poll/", {"device_code": device_code})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        api_key = response.json()["personal_api_key"]

        # Step 4: Verify the API key works
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.pk}/event_definitions/",
            HTTP_AUTHORIZATION=f"Bearer {api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_api_key_has_correct_scopes(self):
        """Test that created API key has only the CLI scopes"""
        # Complete the flow
        response = self.client.post("/api/cli-auth/device-code/")
        device_code = response.json()["device_code"]
        user_code = response.json()["user_code"]

        self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": user_code, "project_id": self.team.id},
        )

        response = self.client.post("/api/cli-auth/poll/", {"device_code": device_code})
        api_key_value = response.json()["personal_api_key"]

        # Get the API key from database
        api_key = PersonalAPIKey.objects.get(secure_value=hash_key_value(api_key_value))

        # Verify scopes
        self.assertEqual(api_key.scopes, CLI_SCOPES)
        self.assertIn("event_definition:read", api_key.scopes)
        self.assertIn("property_definition:read", api_key.scopes)
        self.assertIn("error_tracking:read", api_key.scopes)
        self.assertIn("error_tracking:write", api_key.scopes)

    def test_cross_team_access_is_prevented(self):
        """Test that user cannot authorize CLI for a team in a different organization"""
        # Create a new organization that the user is NOT a member of
        other_org = Organization.objects.create(name="Other Organization")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        # Complete device code request
        response = self.client.post("/api/cli-auth/device-code/")
        user_code = response.json()["user_code"]

        # Try to authorize for the other team
        response = self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": user_code, "project_id": other_team.id},
        )

        # Should be rejected
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["error"], "access_denied")

        # Verify no API key was created
        self.assertEqual(PersonalAPIKey.objects.filter(user=self.user).count(), 0)

    def test_user_can_authorize_for_multiple_teams_in_same_org(self):
        """Test that user can authorize CLI for multiple teams in the same organization"""
        # Create another team in the same organization
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        # Authorize for first team
        response1 = self.client.post("/api/cli-auth/device-code/")
        user_code1 = response1.json()["user_code"]
        self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": user_code1, "project_id": self.team.id},
        )

        # Authorize for second team
        response2 = self.client.post("/api/cli-auth/device-code/")
        user_code2 = response2.json()["user_code"]
        response = self.client.post(
            "/api/cli-auth/authorize/",
            {"user_code": user_code2, "project_id": team2.id},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Both API keys should be created
        self.assertEqual(PersonalAPIKey.objects.filter(user=self.user).count(), 2)
