from datetime import datetime, timedelta

from posthog.test.base import BaseTest
from unittest import mock
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, OrganizationInvite, Plugin
from posthog.models.organization import OrganizationMembership
from posthog.plugins.test.mock import mocked_plugin_requests_get
from posthog.plugins.test.plugin_archives import HELLO_WORLD_PLUGIN_GITHUB_ZIP

from ee.billing.quota_limiting import QuotaResource


class TestOrganization(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_organization_active_invites(self):
        self.assertEqual(self.organization.invites.count(), 0)
        self.assertEqual(self.organization.active_invites.count(), 0)

        OrganizationInvite.objects.create(organization=self.organization)
        self.assertEqual(self.organization.invites.count(), 1)
        self.assertEqual(self.organization.active_invites.count(), 1)

        expired_invite = OrganizationInvite.objects.create(organization=self.organization)
        OrganizationInvite.objects.filter(id=expired_invite.id).update(
            created_at=timezone.now() - timezone.timedelta(hours=73)
        )
        self.assertEqual(self.organization.invites.count(), 2)
        self.assertEqual(self.organization.active_invites.count(), 1)

    @mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
    def test_plugins_are_preinstalled_on_self_hosted(self, mock_get):
        with self.is_cloud(False):
            with self.settings(PLUGINS_PREINSTALLED_URLS=["https://github.com/PostHog/helloworldplugin/"]):
                new_org, _, _ = Organization.objects.bootstrap(
                    self.user,
                    plugins_access_level=Organization.PluginsAccessLevel.INSTALL,
                )

        self.assertEqual(Plugin.objects.filter(organization=new_org, is_preinstalled=True).count(), 1)
        self.assertEqual(
            Plugin.objects.filter(organization=new_org, is_preinstalled=True).get().name,
            "helloworldplugin",
        )
        self.assertEqual(mock_get.call_count, 2)
        mock_get.assert_any_call(
            f"https://github.com/PostHog/helloworldplugin/archive/{HELLO_WORLD_PLUGIN_GITHUB_ZIP[0]}.zip",
            headers={},
        )

    @mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
    def test_plugins_are_not_preinstalled_on_cloud(self, mock_get):
        with self.is_cloud(True):
            with self.settings(PLUGINS_PREINSTALLED_URLS=["https://github.com/PostHog/helloworldplugin/"]):
                new_org, _, _ = Organization.objects.bootstrap(
                    self.user,
                    plugins_access_level=Organization.PluginsAccessLevel.INSTALL,
                )

        self.assertEqual(Plugin.objects.filter(organization=new_org, is_preinstalled=True).count(), 0)
        self.assertEqual(mock_get.call_count, 0)

    def test_plugins_access_level_is_determined_based_on_realm(self):
        with self.is_cloud(True):
            new_org, _, _ = Organization.objects.bootstrap(self.user)
            assert new_org.plugins_access_level == Organization.PluginsAccessLevel.CONFIG

        with self.is_cloud(False):
            new_org, _, _ = Organization.objects.bootstrap(self.user)
            assert new_org.plugins_access_level == Organization.PluginsAccessLevel.ROOT

    def test_update_available_product_features_ignored_if_usage_info_exists(self):
        with self.is_cloud(False):
            new_org, _, _ = Organization.objects.bootstrap(self.user)

            new_org.available_product_features = [{"key": "test1", "name": "test1"}, {"key": "test2", "name": "test2"}]
            new_org.update_available_product_features()
            assert new_org.available_product_features == []

            new_org.available_product_features = [{"key": "test1", "name": "test1"}, {"key": "test2", "name": "test2"}]
            new_org.usage = {"events": {"usage": 1000, "limit": None}}
            new_org.update_available_product_features()
            assert new_org.available_product_features == [
                {"key": "test1", "name": "test1"},
                {"key": "test2", "name": "test2"},
            ]

    def test_session_age_caching(self):
        # Test caching when session_cookie_age is set
        self.organization.session_cookie_age = 3600
        self.organization.save()
        self.assertEqual(cache.get(f"org_session_age:{self.organization.id}"), 3600)

        # Test cache deletion when session_cookie_age is set to None
        self.organization.session_cookie_age = None
        self.organization.save()
        self.assertIsNone(cache.get(f"org_session_age:{self.organization.id}"))

        # Test cache update when session_cookie_age changes
        self.organization.session_cookie_age = 7200
        self.organization.save()
        self.assertEqual(cache.get(f"org_session_age:{self.organization.id}"), 7200)

    @parameterized.expand(
        [
            ("valid_period", {"period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"]}, True),
            (
                "valid_period_with_other_data",
                {"period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"], "events": {"usage": 1000}},
                True,
            ),
            ("no_usage", None, False),
            ("empty_usage", {}, False),
            ("no_period_key", {"events": {"usage": 1000}}, False),
            ("period_none", {"period": None}, False),
            ("period_empty_list", {"period": []}, False),
            ("period_one_element", {"period": ["2024-01-01T00:00:00Z"]}, False),
            ("period_invalid_date_format", {"period": ["invalid", "2024-02-01T00:00:00Z"]}, False),
            ("period_non_iso_format", {"period": ["01/01/2024", "02/01/2024"]}, False),
        ]
    )
    def test_current_billing_period(self, name, usage_data, should_return_period):
        self.organization.usage = usage_data
        self.organization.save()

        result = self.organization.current_billing_period

        if should_return_period:
            self.assertIsNotNone(result)
            assert result is not None  # Type narrowing for mypy
            self.assertIsInstance(result, tuple)
            self.assertEqual(len(result), 2)
            self.assertIsInstance(result[0], datetime)
            self.assertIsInstance(result[1], datetime)
            self.assertLess(result[0], result[1])
        else:
            self.assertIsNone(result)

    @patch("ee.billing.quota_limiting.add_limited_team_tokens")
    def test_limit_product_until_end_of_billing_cycle_success(self, mock_add_limited):
        self.organization.usage = {
            "period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"],
            "events": {"usage": 1000, "limit": 2000},
        }
        self.organization.save()

        expected_timestamp = int(datetime(2024, 2, 1, 0, 0, 0).timestamp())

        self.organization.limit_product_until_end_of_billing_cycle(QuotaResource.EVENTS)

        # Verify add_limited_team_tokens was called correctly
        mock_add_limited.assert_called_once()
        call_args = mock_add_limited.call_args
        self.assertEqual(call_args[0][0], QuotaResource.EVENTS)
        team_tokens = call_args[0][1]
        self.assertIsInstance(team_tokens, dict)
        self.assertEqual(team_tokens[self.team.api_token], expected_timestamp)

        # Verify usage field was updated with quota_limited_until
        self.organization.refresh_from_db()
        self.assertIsNotNone(self.organization.usage["events"]["quota_limited_until"])
        self.assertEqual(self.organization.usage["events"]["quota_limited_until"], expected_timestamp)
        # quota_limiting_suspended_until is set to None, which deletes the key
        self.assertNotIn("quota_limiting_suspended_until", self.organization.usage["events"])

    @patch("ee.billing.quota_limiting.add_limited_team_tokens")
    def test_limit_product_until_end_of_billing_cycle_multiple_teams(self, mock_add_limited):
        second_team = self.organization.teams.create(name="Second Team", api_token="second_token")

        self.organization.usage = {
            "period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"],
            "recordings": {"usage": 500, "limit": 1000},
        }
        self.organization.save()

        expected_timestamp = int(datetime(2024, 2, 1, 0, 0, 0).timestamp())

        self.organization.limit_product_until_end_of_billing_cycle(QuotaResource.RECORDINGS)

        mock_add_limited.assert_called_once()
        team_tokens = mock_add_limited.call_args[0][1]
        self.assertEqual(len(team_tokens), 2)
        self.assertIn(self.team.api_token, team_tokens)
        self.assertIn(second_team.api_token, team_tokens)

        # Verify usage field was updated
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.usage["recordings"]["quota_limited_until"], expected_timestamp)
        # quota_limiting_suspended_until is set to None, which deletes the key
        self.assertNotIn("quota_limiting_suspended_until", self.organization.usage["recordings"])

    @patch("ee.billing.quota_limiting.add_limited_team_tokens")
    def test_limit_product_until_end_of_billing_cycle_creates_resource_usage_if_missing(self, mock_add_limited):
        self.organization.usage = {
            "period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"],
            "events": {"usage": 100, "limit": 200},
        }
        self.organization.save()

        self.organization.limit_product_until_end_of_billing_cycle(QuotaResource.RECORDINGS)

        mock_add_limited.assert_called_once()

        # Note: update_organization_usage_fields requires the resource to exist in usage
        # If it doesn't exist, it logs an error but doesn't fail
        # This test documents this behavior
        self.organization.refresh_from_db()

    @parameterized.expand(
        [
            ("no_usage", None),
            ("empty_usage", {}),
            ("no_period", {"events": {"usage": 1000}}),
            ("invalid_period", {"period": ["invalid"]}),
        ]
    )
    def test_limit_product_until_end_of_billing_cycle_no_billing_period(self, name, usage_data):
        self.organization.usage = usage_data
        self.organization.save()

        with self.assertRaises(RuntimeError) as context:
            self.organization.limit_product_until_end_of_billing_cycle(QuotaResource.EVENTS)

        self.assertIn("Cannot limit without having a billing period", str(context.exception))

    @patch("ee.billing.quota_limiting.remove_limited_team_tokens")
    def test_unlimit_product_success(self, mock_remove_limited):
        self.organization.usage = {
            "period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"],
            "events": {"usage": 1000, "limit": 2000, "quota_limited_until": 1234567890},
        }
        self.organization.save()

        self.organization.unlimit_product(QuotaResource.EVENTS)

        # Verify remove_limited_team_tokens was called correctly
        mock_remove_limited.assert_called_once()
        call_args = mock_remove_limited.call_args
        self.assertEqual(call_args[0][0], QuotaResource.EVENTS)
        team_tokens = call_args[0][1]
        self.assertIsInstance(team_tokens, list)
        self.assertIn(self.team.api_token, team_tokens)

        # Verify usage field was updated - quota_limited_until should be removed
        self.organization.refresh_from_db()
        self.assertNotIn("quota_limited_until", self.organization.usage["events"])
        self.assertNotIn("quota_limiting_suspended_until", self.organization.usage["events"])

    @patch("ee.billing.quota_limiting.remove_limited_team_tokens")
    def test_unlimit_product_multiple_teams(self, mock_remove_limited):
        second_team = self.organization.teams.create(name="Second Team", api_token="second_token")

        self.organization.usage = {
            "period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"],
            "recordings": {
                "usage": 500,
                "limit": 1000,
                "quota_limited_until": 1234567890,
                "quota_limiting_suspended_until": 1234567900,
            },
        }
        self.organization.save()

        self.organization.unlimit_product(QuotaResource.RECORDINGS)

        mock_remove_limited.assert_called_once()
        team_tokens = mock_remove_limited.call_args[0][1]
        self.assertEqual(len(team_tokens), 2)
        self.assertIn(self.team.api_token, team_tokens)
        self.assertIn(second_team.api_token, team_tokens)

        # Verify both limiting fields were removed
        self.organization.refresh_from_db()
        self.assertNotIn("quota_limited_until", self.organization.usage["recordings"])
        self.assertNotIn("quota_limiting_suspended_until", self.organization.usage["recordings"])

    @patch("ee.billing.quota_limiting.remove_limited_team_tokens")
    def test_unlimit_product_no_usage_data(self, mock_remove_limited):
        self.organization.usage = None
        self.organization.save()

        self.organization.unlimit_product(QuotaResource.EVENTS)

        # Should still remove from cache even if no usage data
        mock_remove_limited.assert_called_once()
        team_tokens = mock_remove_limited.call_args[0][1]
        self.assertIn(self.team.api_token, team_tokens)

    @patch("ee.billing.quota_limiting.remove_limited_team_tokens")
    def test_unlimit_product_resource_not_in_usage(self, mock_remove_limited):
        self.organization.usage = {
            "period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"],
            "events": {"usage": 1000, "limit": 2000},
        }
        self.organization.save()

        self.organization.unlimit_product(QuotaResource.RECORDINGS)

        mock_remove_limited.assert_called_once()
        team_tokens = mock_remove_limited.call_args[0][1]
        self.assertIn(self.team.api_token, team_tokens)

    @patch("ee.billing.quota_limiting.get_client")
    def test_get_limited_products_no_teams(self, mock_get_client):
        self.organization.teams.all().delete()
        self.organization.usage = {
            "period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"],
            "events": {"usage": 1000, "limit": 2000, "quota_limited_until": 1234567890},
        }
        self.organization.save()

        result = self.organization.get_limited_products()

        mock_get_client.assert_not_called()
        for _, data in result.items():
            self.assertFalse(data["is_limited_in_redis"])
            self.assertEqual(data["limited_teams"], [])
            self.assertIsNone(data["redis_quota_limited_until"])

    @patch("ee.billing.quota_limiting.get_client")
    def test_get_limited_products_no_limits(self, mock_get_client):
        mock_redis = mock_get_client.return_value
        mock_pipe = mock_redis.pipeline.return_value
        mock_pipe.execute.return_value = [None] * 10

        self.organization.usage = {
            "period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"],
            "events": {"usage": 1000, "limit": 2000},
        }
        self.organization.save()

        result = self.organization.get_limited_products()

        self.assertIn("events", result)
        self.assertFalse(result["events"]["is_limited_in_redis"])
        self.assertEqual(result["events"]["limited_teams"], [])
        self.assertIsNone(result["events"]["redis_quota_limited_until"])
        self.assertIsNone(result["events"]["usage_quota_limited_until"])

    @patch("ee.billing.quota_limiting.get_client")
    def test_get_limited_products_with_redis_limits(self, mock_get_client):
        from ee.billing.quota_limiting import QuotaResource

        future_timestamp = (timezone.now() + timedelta(days=1)).timestamp()

        mock_redis = mock_get_client.return_value
        mock_pipe = mock_redis.pipeline.return_value

        scores: list[float | None] = []
        for resource in QuotaResource:
            if resource == QuotaResource.EVENTS:
                scores.append(future_timestamp)
            else:
                scores.append(None)

        mock_pipe.execute.return_value = scores

        self.organization.usage = {
            "period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"],
            "events": {"usage": 1000, "limit": 2000, "quota_limited_until": 1234567890},
        }
        self.organization.save()

        result = self.organization.get_limited_products()

        self.assertTrue(result["events"]["is_limited_in_redis"])
        self.assertEqual(result["events"]["limited_teams"], [self.team.api_token])
        self.assertEqual(result["events"]["redis_quota_limited_until"], int(future_timestamp))
        self.assertEqual(result["events"]["usage_quota_limited_until"], 1234567890)

    @patch("ee.billing.quota_limiting.get_client")
    def test_get_limited_products_redis_vs_usage_mismatch(self, mock_get_client):
        from ee.billing.quota_limiting import QuotaResource

        future_timestamp = (timezone.now() + timedelta(days=1)).timestamp()

        mock_redis = mock_get_client.return_value
        mock_pipe = mock_redis.pipeline.return_value

        scores: list[float | None] = []
        for resource in QuotaResource:
            if resource == QuotaResource.EVENTS:
                scores.append(future_timestamp)
            else:
                scores.append(None)

        mock_pipe.execute.return_value = scores

        self.organization.usage = {
            "period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"],
            "events": {"usage": 1000, "limit": 2000},
        }
        self.organization.save()

        result = self.organization.get_limited_products()

        self.assertTrue(result["events"]["is_limited_in_redis"])
        self.assertIsNone(result["events"]["usage_quota_limited_until"])

    @patch("ee.billing.quota_limiting.get_client")
    def test_get_limited_products_multiple_teams(self, mock_get_client):
        from ee.billing.quota_limiting import QuotaResource

        second_team = self.organization.teams.create(name="Second Team", api_token="second_token")

        future_timestamp_1 = (timezone.now() + timedelta(days=1)).timestamp()
        future_timestamp_2 = (timezone.now() + timedelta(days=2)).timestamp()

        mock_redis = mock_get_client.return_value
        mock_pipe = mock_redis.pipeline.return_value

        scores: list[float | None] = []
        for resource in QuotaResource:
            if resource == QuotaResource.EVENTS:
                scores.append(future_timestamp_1)
                scores.append(future_timestamp_2)
            else:
                scores.append(None)
                scores.append(None)

        mock_pipe.execute.return_value = scores

        self.organization.usage = {
            "period": ["2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z"],
            "events": {"usage": 1000, "limit": 2000, "quota_limited_until": 1234567890},
        }
        self.organization.save()

        result = self.organization.get_limited_products()

        self.assertTrue(result["events"]["is_limited_in_redis"])
        self.assertEqual(len(result["events"]["limited_teams"]), 2)
        self.assertIn(self.team.api_token, result["events"]["limited_teams"])
        self.assertIn(second_team.api_token, result["events"]["limited_teams"])
        self.assertEqual(
            result["events"]["redis_quota_limited_until"], int(max(future_timestamp_1, future_timestamp_2))
        )


class TestOrganizationMembership(BaseTest):
    @patch("posthoganalytics.capture")
    def test_event_sent_when_membership_level_changed(
        self,
        mock_capture,
    ):
        user = self._create_user("user1")
        organization = Organization.objects.create(name="Test Org")
        membership = OrganizationMembership.objects.create(user=user, organization=organization, level=1)
        mock_capture.assert_not_called()
        # change the level
        membership.level = 15
        membership.save()
        # check that the event was sent
        mock_capture.assert_called_once_with(
            event="membership level changed",
            distinct_id=user.distinct_id,
            properties={"new_level": 15, "previous_level": 1, "$set": mock.ANY},
            groups=mock.ANY,
        )
