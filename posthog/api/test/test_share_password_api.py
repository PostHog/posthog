import json
from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from rest_framework import status
from rest_framework.test import APIRequestFactory

from posthog.api.test.test_sharing import mock_exporter_template
from posthog.constants import AvailableFeature
from posthog.models import SharePassword, SharingConfiguration
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.rate_limit import SharePasswordThrottle, SharePasswordVolumeThrottle

from products.dashboards.backend.models.dashboard import Dashboard


class TestSharePasswordAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Enable access control feature for the organization
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            }
        ]
        self.organization.save()

        self.dashboard = Dashboard.objects.create(team=self.team, name="Test Dashboard", created_by=self.user)
        self.sharing_config = SharingConfiguration.objects.create(
            team=self.team, dashboard=self.dashboard, enabled=True, password_required=True
        )

    def test_create_password_with_custom_password(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/",
            data=json.dumps({"raw_password": "my-secure-password", "note": "Test password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        self.assertEqual(data["password"], "my-secure-password")
        self.assertEqual(data["note"], "Test password")
        self.assertEqual(data["created_by_email"], self.user.email)
        self.assertIn("id", data)
        self.assertIn("created_at", data)

        # Verify password was created in database
        share_password = SharePassword.objects.get(id=data["id"])
        self.assertTrue(share_password.check_password("my-secure-password"))
        self.assertEqual(share_password.note, "Test password")

    def test_create_password_with_generated_password(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/",
            data=json.dumps({"note": "Auto-generated password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        # Should have generated a secure password
        self.assertIsNotNone(data["password"])
        self.assertTrue(len(data["password"]) >= 16)
        self.assertEqual(data["note"], "Auto-generated password")

        # Verify password works
        share_password = SharePassword.objects.get(id=data["id"])
        self.assertTrue(share_password.check_password(data["password"]))

    def test_create_password_without_password_protection_enabled(self):
        # Disable password protection
        self.sharing_config.password_required = False
        self.sharing_config.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/",
            data=json.dumps({"raw_password": "test-password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Password protection must be enabled", response.json()["error"])

    def test_create_password_without_access_control(self):
        # Mock organization without access control
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/",
            data=json.dumps({"raw_password": "test-password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Access Control feature", response.json()["error"])

    def test_create_password_validation_too_short(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/",
            data=json.dumps({"raw_password": "short"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("at least 8 characters", str(response.json()))

    def test_delete_password(self):
        # Create a password first
        share_password, _ = SharePassword.create_password(
            sharing_configuration=self.sharing_config,
            created_by=self.user,
            raw_password="test-password",
            note="To be deleted",
        )

        response = self.client.delete(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/{share_password.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify password was deactivated
        share_password.refresh_from_db()
        self.assertFalse(share_password.is_active)

    def test_delete_nonexistent_password(self):
        response = self.client.delete(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/99999/"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("Password not found", response.json()["detail"])

    def test_delete_password_without_access_control(self):
        share_password, _ = SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="test-password"
        )

        # Mock organization without access control
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.delete(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/{share_password.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Access Control feature", response.json()["error"])

    def test_password_validation_in_sharing_viewer(self):
        """Test that password validation works correctly in the sharing viewer."""
        # Create a password
        share_password, raw_password = SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="secure-test-password"
        )

        # Test with correct password
        response = self.client.post(
            f"/shared/{self.sharing_config.access_token}",
            data=json.dumps({"password": raw_password}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("shareToken", response.json())

        # Test with incorrect password
        response = self.client.post(
            f"/shared/{self.sharing_config.access_token}",
            data=json.dumps({"password": "wrong-password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Incorrect password", response.json()["error"])

    def test_repeated_wrong_passwords_are_throttled(self):
        SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="secure-test-password"
        )

        statuses = []
        throttled_response = None
        for attempt in range(25):
            # Each guess comes from a different address, so the budget has to follow the share link
            source_ip = f"10.0.0.{attempt}"
            response = self.client.post(
                f"/shared/{self.sharing_config.access_token}",
                data=json.dumps({"password": f"wrong-password-{attempt}"}),
                content_type="application/json",
                REMOTE_ADDR=source_ip,
                HTTP_X_FORWARDED_FOR=source_ip,
            )
            statuses.append(response.status_code)
            if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                throttled_response = response
                break

        self.assertEqual(statuses[0], status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(statuses[-1], status.HTTP_429_TOO_MANY_REQUESTS)
        assert throttled_response is not None
        self.assertEqual(throttled_response["Retry-After"], "60")

        # A throttled guess never reaches password validation, so it must not log an attempt -
        # otherwise a flood logs at the volume throttle's rate instead of the wrong-guess one.
        failed_attempt_logs = ActivityLog.objects.filter(
            activity="share_login_failed", item_id=str(self.dashboard.id)
        ).count()
        self.assertEqual(failed_attempt_logs, statuses.count(status.HTTP_401_UNAUTHORIZED))

    def test_attempts_are_counted_atomically(self):
        # Submissions that arrive together must each consume budget. A read-modify-write throttle
        # lets them all read the same below-limit state and overwrite each other, so the cap only
        # holds for strictly serial guessing - which an attacker has no reason to do.
        SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="secure-test-password"
        )
        throttle = SharePasswordThrottle()
        request = APIRequestFactory().post(f"/shared/{self.sharing_config.access_token}")
        view = SimpleNamespace(kwargs={"access_token": self.sharing_config.access_token})

        key = throttle.get_cache_key(request, view)  # type: ignore[arg-type]
        cache.delete(key)
        for _ in range(3):
            throttle.allow_request(request, view)  # type: ignore[arg-type]

        self.assertEqual(cache.get(key), 3)

    def test_correct_password_succeeds_after_wrong_guess_budget_exhausted(self):
        # SharePasswordThrottle's budget is shared by every viewer of a link, keyed only on the
        # token. If a wrong guess and a correct one both drew from it, an attacker holding just
        # the URL could submit garbage passwords to deny everyone else who knows the real one.
        SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="secure-test-password"
        )

        statuses = []
        for attempt in range(15):
            source_ip = f"10.0.1.{attempt}"
            wrong_response = self.client.post(
                f"/shared/{self.sharing_config.access_token}",
                data=json.dumps({"password": f"wrong-password-{attempt}"}),
                content_type="application/json",
                REMOTE_ADDR=source_ip,
                HTTP_X_FORWARDED_FOR=source_ip,
            )
            statuses.append(wrong_response.status_code)
            if wrong_response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                break

        self.assertEqual(statuses[-1], status.HTTP_429_TOO_MANY_REQUESTS)

        correct_response = self.client.post(
            f"/shared/{self.sharing_config.access_token}",
            data=json.dumps({"password": "secure-test-password"}),
            content_type="application/json",
            REMOTE_ADDR="10.0.2.1",
            HTTP_X_FORWARDED_FOR="10.0.2.1",
        )

        self.assertEqual(correct_response.status_code, status.HTTP_200_OK)
        self.assertIn("shareToken", correct_response.json())

    def test_volume_throttle_caps_attempts_regardless_of_correctness(self):
        # SharePasswordThrottle only meters wrong guesses, so nothing else bounds sheer POST
        # volume - and thus password-hashing cost - per link. SharePasswordVolumeThrottle is
        # that backstop; losing it from throttle_classes would leave submissions uncapped.
        throttle = SharePasswordVolumeThrottle()
        request = APIRequestFactory().post(f"/shared/{self.sharing_config.access_token}")
        view = SimpleNamespace(kwargs={"access_token": self.sharing_config.access_token})

        key = throttle.get_cache_key(request, view)  # type: ignore[arg-type]
        cache.delete(key)
        results = [throttle.allow_request(request, view) for _ in range(throttle.num_requests + 1)]  # type: ignore[arg-type]

        self.assertTrue(all(results[: throttle.num_requests]))
        self.assertFalse(results[-1])

    @mock_exporter_template
    def test_head_request_does_not_bypass_password_gate(self):
        SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="secure-test-password"
        )

        head_response = self.client.head(f"/shared/{self.sharing_config.access_token}")
        unlock_page = self.client.get(f"/shared/{self.sharing_config.access_token}")

        self.assertEqual(head_response.status_code, status.HTTP_200_OK)
        # Django strips HEAD bodies, so compare against the unlock page an anonymous GET receives
        self.assertEqual(head_response["Content-Length"], unlock_page["Content-Length"])
        # Rendering the shared dashboard stamps last_accessed_at, so it stays unset while locked
        self.dashboard.refresh_from_db()
        self.assertIsNone(self.dashboard.last_accessed_at)

    @mock_exporter_template
    def test_jwt_token_invalidation_on_password_deletion(self):
        """Test that JWT tokens are invalidated when their associated password is deleted, but remain valid when other passwords are deleted."""
        # Create two passwords
        password1, raw_password1 = SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="password1", note="Password 1"
        )
        password2, raw_password2 = SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="password2", note="Password 2"
        )

        # Authenticate with password1 to get JWT token
        response = self.client.post(
            f"/shared/{self.sharing_config.access_token}",
            data=json.dumps({"password": raw_password1}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        jwt_token1 = response.json()["shareToken"]

        # Authenticate with password2 to get another JWT token
        response = self.client.post(
            f"/shared/{self.sharing_config.access_token}",
            data=json.dumps({"password": raw_password2}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        jwt_token2 = response.json()["shareToken"]

        # Verify both JWT tokens work initially
        response = self.client.get(
            f"/shared/{self.sharing_config.access_token}",
            headers={"authorization": f"Bearer {jwt_token1}", "accept": "application/json"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(
            f"/shared/{self.sharing_config.access_token}",
            headers={"authorization": f"Bearer {jwt_token2}", "accept": "application/json"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Delete password2 (not the one used for jwt_token1)
        response = self.client.delete(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/{password2.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # jwt_token1 should still be valid since it was created with password1
        response = self.client.get(
            f"/shared/{self.sharing_config.access_token}",
            headers={"authorization": f"Bearer {jwt_token1}", "accept": "application/json"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should contain dashboard data, not unlock page
        self.assertIn("dashboard", response.json())

        # jwt_token2 should now be invalid since password2 was deleted
        response = self.client.get(
            f"/shared/{self.sharing_config.access_token}",
            headers={"authorization": f"Bearer {jwt_token2}", "accept": "application/json"},
        )
        # Should not be authenticated anymore, so should show unlock page
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Since authentication failed, response is HTML with unlock page text
        response_text = response.content.decode("utf-8")
        self.assertIn('{"type": "unlock"}', response_text)

        # Now delete password1
        response = self.client.delete(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/{password1.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # jwt_token1 should now also be invalid
        response = self.client.get(
            f"/shared/{self.sharing_config.access_token}",
            headers={"authorization": f"Bearer {jwt_token1}", "accept": "application/json"},
        )
        # Should not be authenticated anymore, so should show unlock page
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Since authentication failed, response is HTML with unlock page text
        response_text = response.content.decode("utf-8")
        self.assertIn('{"type": "unlock"}', response_text)

    @patch("posthog.rate_limit.is_rate_limit_enabled")
    def test_sharing_view_works_with_rate_limiting_enabled(self, mock_is_rate_limit_enabled):
        """
        Test that ensures sharing views work correctly when rate limiting is enabled.
        This test specifically verifies that request.user is properly set before throttle checks,
        preventing AttributeError: 'NoneType' object has no attribute 'is_authenticated'
        """
        # Force rate limiting to be enabled
        mock_is_rate_limit_enabled.return_value = True

        password, raw_password = SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="testpass123"
        )

        # Test that we can authenticate with password (this would fail with 500 error if request.user is None during throttle checks)
        response = self.client.post(
            f"/shared/{self.sharing_config.access_token}",
            data=json.dumps({"password": raw_password}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("shareToken", response.json())

        # Test that we can access the shared content (this would also fail if throttle checks break)
        response = self.client.get(f"/shared/{self.sharing_config.access_token}")
        # Should get unlock page (HTML response, not 500 error)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("text/html", response.get("Content-Type", ""))

    @mock_exporter_template
    def test_unlock_page_respects_whitelabel_setting(self):
        """
        Test that the unlock (password login) page respects the whitelabel setting
        stored in the sharing configuration settings.
        """
        # Enable white labelling feature for the organization
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.WHITE_LABELLING, "name": AvailableFeature.WHITE_LABELLING},
        ]
        self.organization.save()

        # Set whitelabel in the sharing configuration settings
        self.sharing_config.settings = {"whitelabel": True}
        self.sharing_config.save()

        # Create a password so the unlock page is required
        SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="testpass123"
        )

        # Access the shared resource without authentication - should show unlock page
        response = self.client.get(f"/shared/{self.sharing_config.access_token}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # The unlock page should include whitelabel: true in the exported data
        response_content = response.content.decode("utf-8")
        self.assertIn('"type": "unlock"', response_content)
        self.assertIn('"whitelabel": true', response_content)
