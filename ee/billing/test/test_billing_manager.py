import datetime
from typing import Any, cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import jwt
from parameterized import parameterized
from rest_framework.exceptions import NotAuthenticated

from posthog.cloud_utils import TEST_clear_instance_license_cache
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from ee.billing.billing_manager import BillingManager, _get_user_organization_role, build_billing_token
from ee.billing.billing_types import Product
from ee.models.license import License, LicenseManager


def create_default_products_response(**kwargs) -> dict[str, list[Product]]:
    data: Any = {
        "products": [
            Product(
                name="Product analytics",
                headline="Product analytics with autocapture",
                description="A comprehensive product analytics platform built to natively work with session replay, feature flags, experiments, and surveys.",
                usage_key="events",
                image_url="https://posthog.com/images/products/product-analytics/product-analytics.png",
                docs_url="https://posthog.com/docs/product-analytics",
                type="product_analytics",
                unit="event",
                contact_support=False,
                inclusion_only=False,
                icon_key="IconGraph",
                plans=[],
                addons=[],
            )
        ]
    }

    data.update(kwargs)
    return data


class TestBillingManager(BaseTest):
    @patch(
        "ee.billing.billing_manager.requests.get",
        return_value=MagicMock(
            status_code=200, json=MagicMock(return_value={"products": create_default_products_response()})
        ),
    )
    def test_get_billing_unlicensed(self, billing_patch_request_mock):
        organization = self.organization
        TEST_clear_instance_license_cache()

        BillingManager(license=None).get_billing(organization)
        assert billing_patch_request_mock.call_count == 1
        billing_patch_request_mock.assert_called_with(
            "https://billing.posthog.com/api/products-v2", params={"plan": "standard"}, headers={}
        )

    @patch(
        "ee.billing.billing_manager.requests.patch",
        return_value=MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"})),
    )
    def test_update_billing_organization_users(self, billing_patch_request_mock: MagicMock):
        organization = self.organization
        license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )
        y = User.objects.create_and_join(
            organization=organization,
            email="y@x.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )
        organization.refresh_from_db()
        assert len(organization.members.values_list("distinct_id", flat=True)) == 2  # one exists in the test base
        BillingManager(license).update_billing_organization_users(organization)
        assert billing_patch_request_mock.call_count == 1
        assert len(billing_patch_request_mock.call_args[1]["json"]["distinct_ids"]) == 2
        assert billing_patch_request_mock.call_args[1]["json"]["org_customer_email"] == "y@x.com"
        assert billing_patch_request_mock.call_args[1]["json"]["org_admin_emails"] == ["y@x.com"]
        assert billing_patch_request_mock.call_args[1]["json"]["org_users"] == [
            {"email": "y@x.com", "distinct_id": y.distinct_id, "role": 15},
        ]

    @patch(
        "ee.billing.billing_manager.requests.patch",
        return_value=MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"})),
    )
    def test_update_billing_organization_users_with_multiple_members(self, billing_patch_request_mock: MagicMock):
        organization = self.organization
        license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )
        User.objects.create_and_join(
            organization=organization,
            email="y1@x.com",
            first_name="y1",
            last_name="y1",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )
        y2 = User.objects.create_and_join(
            organization=organization,
            email="y2@x.com",
            first_name="y2",
            last_name="y2",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )
        y3 = User.objects.create_and_join(
            organization=organization,
            email="y3@x.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )
        organization.refresh_from_db()
        BillingManager(license).update_billing_organization_users(organization)
        assert billing_patch_request_mock.call_count == 1
        assert len(billing_patch_request_mock.call_args[1]["json"]["distinct_ids"]) == 4
        assert billing_patch_request_mock.call_args[1]["json"]["org_customer_email"] == "y3@x.com"
        assert sorted(billing_patch_request_mock.call_args[1]["json"]["org_admin_emails"]) == ["y2@x.com", "y3@x.com"]
        assert billing_patch_request_mock.call_args[1]["json"]["org_users"] == [
            {"email": "y2@x.com", "distinct_id": y2.distinct_id, "role": 8},
            {"email": "y3@x.com", "distinct_id": y3.distinct_id, "role": 15},
        ]

    @patch("posthoganalytics.capture")
    def test_update_org_details_preserves_quota_limits(self, patch_capture):
        organization = self.organization
        organization.usage = {
            "events": {
                "usage": 90,
                "limit": 1000,
                "todays_usage": 10,
                "quota_limited_until": 1612137599,
            },
            "exceptions": {
                "usage": 10,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
            "recordings": {
                "usage": 15,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
            "rows_synced": {"usage": 45, "limit": 500, "todays_usage": 5},
            "rows_exported": {"usage": 10, "limit": 1000, "todays_usage": 5},
            "feature_flag_requests": {"usage": 25, "limit": 300, "todays_usage": 5},
            "api_queries_read_bytes": {"usage": 1000, "limit": 1000000, "todays_usage": 500},
            "llm_events": {"usage": 50, "limit": 1000, "todays_usage": 2},
            "ai_credits": {"usage": 1200, "limit": 20000, "todays_usage": 150},
            "cdp_trigger_events": {"usage": 10, "limit": 100, "todays_usage": 5},
            "workflow_emails": {"usage": 100, "limit": 10000, "todays_usage": 10},
            "workflow_destinations_dispatched": {"usage": 50, "limit": 10000, "todays_usage": 5},
            "logs_gb_ingested": {"usage": 5.5, "limit": 50, "todays_usage": 0.5},
            "period": ["2024-01-01T00:00:00Z", "2024-01-31T23:59:59Z"],
            "survey_responses": {
                "usage": 10,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
        }
        organization.save()

        license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key123::key123",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )

        billing_status = {
            "customer": {
                "usage_summary": {
                    "events": {"usage": 90, "limit": 1000},
                    "exceptions": {"usage": 10, "limit": 100},
                    "recordings": {"usage": 15, "limit": 100},
                    "rows_synced": {"usage": 45, "limit": 500},
                    "rows_exported": {"usage": 10, "limit": 1000},
                    "feature_flag_requests": {"usage": 25, "limit": 300},
                    "api_queries_read_bytes": {"usage": 1000, "limit": 1000000},
                    "llm_events": {"usage": 50, "limit": 1000},
                    "ai_credits": {"usage": 1200, "limit": 20000, "todays_usage": 150},
                    "survey_responses": {"usage": 10, "limit": 100},
                    "cdp_trigger_events": {"usage": 10, "limit": 100},
                    "workflow_emails": {"usage": 100, "limit": 10000},
                    "workflow_destinations_dispatched": {"usage": 50, "limit": 10000},
                    "logs_gb_ingested": {"usage": 5.5, "limit": 50},
                },
                "billing_period": {
                    "current_period_start": "2024-01-01T00:00:00Z",
                    "current_period_end": "2024-01-31T23:59:59Z",
                },
            }
        }

        BillingManager(license).update_org_details(organization, billing_status)
        organization.refresh_from_db()

        assert organization.usage == {
            "events": {
                "usage": 90,
                "limit": 1000,
                "todays_usage": 10,
                "quota_limited_until": 1612137599,
            },
            "exceptions": {
                "usage": 10,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
            "recordings": {
                "usage": 15,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
            "rows_synced": {"usage": 45, "limit": 500, "todays_usage": 5},
            "rows_exported": {"usage": 10, "limit": 1000, "todays_usage": 5},
            "feature_flag_requests": {"usage": 25, "limit": 300, "todays_usage": 5},
            "llm_events": {"usage": 50, "limit": 1000, "todays_usage": 2},
            "ai_credits": {"usage": 1200, "limit": 20000, "todays_usage": 150},
            "workflow_emails": {"usage": 100, "limit": 10000, "todays_usage": 10},
            "workflow_destinations_dispatched": {"usage": 50, "limit": 10000, "todays_usage": 5},
            "logs_gb_ingested": {"usage": 5.5, "limit": 50, "todays_usage": 0.5},
            "period": ["2024-01-01T00:00:00Z", "2024-01-31T23:59:59Z"],
            "api_queries_read_bytes": {"usage": 1000, "limit": 1000000, "todays_usage": 500},
            "cdp_trigger_events": {"usage": 10, "limit": 100, "todays_usage": 5},
            "survey_responses": {
                "usage": 10,
                "limit": 100,
                "todays_usage": 5,
                "quota_limiting_suspended_until": 1611705600,
            },
        }


class TestBuildBillingToken(BaseTest):
    def setUp(self):
        super().setUp()
        self.license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="license_id::license_secret",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )

    def test_build_billing_token_without_user(self):
        """Token without user should have basic organization info only"""
        token = build_billing_token(self.license, self.organization)

        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        assert decoded["id"] == "license_id"
        assert decoded["organization_id"] == str(self.organization.id)
        assert decoded["organization_name"] == self.organization.name
        assert decoded["aud"] == "posthog:license-key"
        assert "distinct_id" not in decoded
        assert "organization_role" not in decoded
        assert "original_role" not in decoded

    def test_build_billing_token_with_user_who_is_member(self):
        """Token with user should include distinct_id and organization_role as level display string"""
        token = build_billing_token(self.license, self.organization, user=self.user)

        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        assert decoded["id"] == "license_id"
        assert decoded["organization_id"] == str(self.organization.id)
        assert decoded["distinct_id"] == str(self.user.distinct_id)
        # organization_role should be a level display string (e.g., "member", "administrator", "owner")
        assert decoded["organization_role"] in ["member", "administrator", "owner"]
        assert "original_role" not in decoded

    def test_build_billing_token_raises_when_no_organization(self):
        """Should raise NotAuthenticated when organization is None"""
        with self.assertRaises(NotAuthenticated):
            build_billing_token(self.license, None)

    def test_build_billing_token_raises_when_no_license(self):
        """Should raise NotAuthenticated when license is None"""
        with self.assertRaises(NotAuthenticated):
            build_billing_token(None, self.organization)

    def test_build_billing_token_raises_when_user_not_in_organization(self):
        """Should raise NotAuthenticated when user (acting as authorizer) is not a member of the organization"""
        other_org = Organization.objects.create(name="Other Org")
        non_member_user = User.objects.create_and_join(
            organization=other_org,
            email="nonmember@example.com",
            password=None,
        )

        with self.assertRaises(NotAuthenticated) as ctx:
            build_billing_token(self.license, self.organization, user=non_member_user)

        # When user is provided without authorizer_actor, user becomes the authorizer
        assert "Authorizer is not part of organization" in str(ctx.exception.detail)

    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_build_billing_token_with_authorizer_actor_same_as_user(self, mock_capture):
        """When authorizer_actor equals user, no privilege escalation occurs"""
        token = build_billing_token(self.license, self.organization, user=self.user, authorizer_actor=self.user)

        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        assert decoded["distinct_id"] == str(self.user.distinct_id)
        assert decoded["organization_role"] in ["member", "administrator", "owner"]
        assert "original_role" not in decoded
        mock_capture.assert_not_called()

    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_build_billing_token_with_privilege_escalation(self, mock_capture):
        """When authorizer_actor differs from user, original_role is set and capture is called"""
        member_user = User.objects.create_and_join(
            organization=self.organization,
            email="member@example.com",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )
        admin_authorizer = User.objects.create_and_join(
            organization=self.organization,
            email="admin@example.com",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )

        token = build_billing_token(
            self.license, self.organization, user=member_user, authorizer_actor=admin_authorizer
        )

        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        assert decoded["distinct_id"] == str(member_user.distinct_id)
        # organization_role should be the authorizer's role (administrator)
        assert decoded["organization_role"] == "administrator"
        # original_role should be the user's actual role (member)
        assert decoded["original_role"] == "member"

        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        assert call_kwargs["event"] == "$billing_privilege_escalation"
        assert call_kwargs["distinct_id"] == str(member_user.distinct_id)
        assert call_kwargs["properties"]["authorizer_actor_id"] == admin_authorizer.id
        assert call_kwargs["properties"]["action"] == "update_billing"

    def test_build_billing_token_raises_when_authorizer_actor_not_in_organization(self):
        """Should raise NotAuthenticated when authorizer_actor is not a member of the organization"""
        other_org = Organization.objects.create(name="Other Org")
        non_member_authorizer = User.objects.create_and_join(
            organization=other_org,
            email="nonmember_authorizer@example.com",
            password=None,
        )

        with self.assertRaises(NotAuthenticated) as ctx:
            build_billing_token(self.license, self.organization, user=self.user, authorizer_actor=non_member_authorizer)

        assert "Authorizer is not part of organization" in str(ctx.exception.detail)

    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_build_billing_token_privilege_escalation_user_not_member_allowed(self, mock_capture):
        """When authorizer_actor is valid but user is not a member, original_role should be None"""
        other_org = Organization.objects.create(name="Other Org")
        non_member_user = User.objects.create_and_join(
            organization=other_org,
            email="nonmember@example.com",
            password=None,
        )
        valid_authorizer = User.objects.create_and_join(
            organization=self.organization,
            email="valid_authorizer@example.com",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )

        token = build_billing_token(
            self.license, self.organization, user=non_member_user, authorizer_actor=valid_authorizer
        )

        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        # Token should have non-member user's distinct_id
        assert decoded["distinct_id"] == str(non_member_user.distinct_id)
        # organization_role should be the authorizer's role
        assert decoded["organization_role"] == "administrator"
        # original_role should be None since user is not a member
        assert decoded["original_role"] is None

        # Privilege escalation capture should still be called
        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        assert call_kwargs["event"] == "$billing_privilege_escalation"
        assert call_kwargs["distinct_id"] == str(non_member_user.distinct_id)
        assert call_kwargs["properties"]["authorizer_actor_id"] == valid_authorizer.id

    @parameterized.expand(
        [
            (OrganizationMembership.Level.MEMBER, "member"),
            (OrganizationMembership.Level.ADMIN, "administrator"),
            (OrganizationMembership.Level.OWNER, "owner"),
        ]
    )
    def test_build_billing_token_user_role_populated_for_all_levels(self, level, expected_role_display):
        """organization_role should be the correct level display string for each membership level"""
        user_with_level = User.objects.create_and_join(
            organization=self.organization,
            email=f"user_level_{level}@example.com",
            password=None,
            level=level,
        )

        token = build_billing_token(self.license, self.organization, user=user_with_level)

        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        assert decoded["organization_role"] == expected_role_display

    def test_build_billing_token_without_user_but_with_authorizer_actor(self):
        """When user is None but authorizer_actor is provided, authorizer_actor should be ignored"""
        admin_user = User.objects.create_and_join(
            organization=self.organization,
            email="admin@example.com",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )

        token = build_billing_token(self.license, self.organization, user=None, authorizer_actor=admin_user)

        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        # Without user, no user-related fields should be in the token
        assert "distinct_id" not in decoded
        assert "organization_role" not in decoded
        assert "original_role" not in decoded


class TestGetUserOrganizationRole(BaseTest):
    def test_returns_role_display_for_valid_member(self):
        """Should return the role display string for a user who is a member"""
        role_display = _get_user_organization_role(self.user, self.organization)
        # Should be a valid role display string
        assert role_display in ["member", "administrator", "owner"]

    @parameterized.expand(
        [
            (OrganizationMembership.Level.MEMBER, "member"),
            (OrganizationMembership.Level.ADMIN, "administrator"),
            (OrganizationMembership.Level.OWNER, "owner"),
        ]
    )
    def test_returns_correct_role_display_for_each_level(self, level, expected_display):
        """Should return the correct display string for each membership level"""
        user_with_level = User.objects.create_and_join(
            organization=self.organization,
            email=f"user_level_{level}_helper@example.com",
            password=None,
            level=level,
        )
        role_display = _get_user_organization_role(user_with_level, self.organization)
        assert role_display == expected_display

    def test_returns_none_for_non_member(self):
        """Should return None for a user who is not a member"""
        other_org = Organization.objects.create(name="Other Org")
        non_member = User.objects.create_and_join(
            organization=other_org,
            email="nonmember@example.com",
            password=None,
        )

        role_display = _get_user_organization_role(non_member, self.organization)
        assert role_display is None


class TestUpdateBillingOrganizationUsersPrivilegeEscalation(BaseTest):
    """Tests for update_billing_organization_users privilege escalation behavior"""

    def setUp(self):
        super().setUp()
        self.license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="license_id::license_secret",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )

    @patch("ee.billing.billing_manager.requests.patch")
    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_update_billing_org_users_uses_owner_as_authorizer_actor(self, mock_capture, mock_patch):
        """
        When BillingManager is initialized with a non-owner user but calls update_billing_organization_users,
        the billing token should use the owner's role (privilege escalation) and capture the event.
        """
        mock_patch.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"}))

        # Create an owner for the organization
        owner = User.objects.create_and_join(
            organization=self.organization,
            email="owner@example.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )

        # Create a regular member - this will be the user in BillingManager
        member = User.objects.create_and_join(
            organization=self.organization,
            email="member@example.com",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )

        # BillingManager is initialized with the member user
        billing_manager = BillingManager(self.license, user=member)
        billing_manager.update_billing_organization_users(self.organization)

        # Verify the PATCH request was made
        mock_patch.assert_called_once()

        # Extract the Authorization header and decode the JWT
        call_kwargs = mock_patch.call_args
        auth_header = call_kwargs[1]["headers"]["Authorization"]
        token = auth_header.replace("Bearer ", "")
        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        # Token should have member's distinct_id
        assert decoded["distinct_id"] == str(member.distinct_id)
        # organization_role should be the owner's role (privilege escalation)
        assert decoded["organization_role"] == "owner"
        # original_role should be the member's actual role
        assert decoded["original_role"] == "member"

        # Verify posthoganalytics.capture was called for privilege escalation
        mock_capture.assert_called_once()
        capture_kwargs = mock_capture.call_args[1]
        assert capture_kwargs["event"] == "$billing_privilege_escalation"
        assert capture_kwargs["distinct_id"] == str(member.distinct_id)
        assert capture_kwargs["properties"]["authorizer_actor_id"] == owner.id
        assert capture_kwargs["properties"]["action"] == "update_billing"

    @patch("ee.billing.billing_manager.requests.patch")
    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_update_billing_org_users_no_escalation_when_user_is_owner(self, mock_capture, mock_patch):
        """
        When BillingManager user is the owner, no privilege escalation should occur.
        """
        mock_patch.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"}))

        # Create an owner for the organization
        owner = User.objects.create_and_join(
            organization=self.organization,
            email="owner@example.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )

        # BillingManager is initialized with the owner user
        billing_manager = BillingManager(self.license, user=owner)
        billing_manager.update_billing_organization_users(self.organization)

        mock_patch.assert_called_once()

        # Extract and decode the JWT
        call_kwargs = mock_patch.call_args
        auth_header = call_kwargs[1]["headers"]["Authorization"]
        token = auth_header.replace("Bearer ", "")
        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        # Token should have owner's distinct_id
        assert decoded["distinct_id"] == str(owner.distinct_id)
        # organization_role should be owner
        assert decoded["organization_role"] == "owner"
        # original_role should NOT be present (no escalation)
        assert "original_role" not in decoded

        # No privilege escalation capture should occur
        mock_capture.assert_not_called()

    @patch("ee.billing.billing_manager.requests.patch")
    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_update_billing_org_users_uses_most_recent_owner(self, mock_capture, mock_patch):
        """
        When multiple owners exist, should use the most recently joined owner as authorizer.
        """
        mock_patch.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"}))

        # Create two owners with different join times
        older_owner = User.objects.create_and_join(
            organization=self.organization,
            email="older_owner@example.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )
        # Update the joined_at to be older
        membership = OrganizationMembership.objects.get(user=older_owner, organization=self.organization)
        membership.joined_at = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
        membership.save()

        newer_owner = User.objects.create_and_join(
            organization=self.organization,
            email="newer_owner@example.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )

        member = User.objects.create_and_join(
            organization=self.organization,
            email="member@example.com",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )

        billing_manager = BillingManager(self.license, user=member)
        billing_manager.update_billing_organization_users(self.organization)

        mock_patch.assert_called_once()

        # Verify that the capture was called with the newer owner as authorizer
        mock_capture.assert_called_once()
        capture_kwargs = mock_capture.call_args[1]
        assert capture_kwargs["properties"]["authorizer_actor_id"] == newer_owner.id

    @patch("ee.billing.billing_manager.requests.patch")
    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_update_billing_org_users_admin_gets_escalated_to_owner(self, mock_capture, mock_patch):
        """
        When BillingManager user is an admin, they should be escalated to owner role.
        """
        mock_patch.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"}))

        owner = User.objects.create_and_join(
            organization=self.organization,
            email="owner@example.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )

        admin = User.objects.create_and_join(
            organization=self.organization,
            email="admin@example.com",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )

        billing_manager = BillingManager(self.license, user=admin)
        billing_manager.update_billing_organization_users(self.organization)

        mock_patch.assert_called_once()

        call_kwargs = mock_patch.call_args
        auth_header = call_kwargs[1]["headers"]["Authorization"]
        token = auth_header.replace("Bearer ", "")
        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        assert decoded["distinct_id"] == str(admin.distinct_id)
        assert decoded["organization_role"] == "owner"
        assert decoded["original_role"] == "administrator"

        mock_capture.assert_called_once()
        capture_kwargs = mock_capture.call_args[1]
        assert capture_kwargs["distinct_id"] == str(admin.distinct_id)
        assert capture_kwargs["properties"]["authorizer_actor_id"] == owner.id

    @patch("ee.billing.billing_manager.capture_exception")
    @patch("ee.billing.billing_manager.requests.patch")
    def test_update_billing_org_users_no_owner_captures_exception(self, mock_patch, mock_capture_exception):
        """
        When organization has no owner, should capture exception and return early.
        """
        # Remove the default user's ownership if any
        OrganizationMembership.objects.filter(organization=self.organization).update(
            level=OrganizationMembership.Level.MEMBER
        )

        billing_manager = BillingManager(self.license, user=self.user)
        billing_manager.update_billing_organization_users(self.organization)

        # Should not make any PATCH request
        mock_patch.assert_not_called()

        # Should capture exception about no owner
        mock_capture_exception.assert_called_once()
        exception_call = mock_capture_exception.call_args
        assert "No owner membership found" in str(exception_call[0][0])

    @patch("ee.billing.billing_manager.requests.patch")
    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_update_billing_org_users_without_billing_manager_user(self, mock_capture, mock_patch):
        """
        When BillingManager has no user (user=None), no privilege escalation should occur
        since there's no user to escalate.
        """
        mock_patch.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"}))

        # Create an owner (required for the function to work)
        User.objects.create_and_join(
            organization=self.organization,
            email="owner@example.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )

        # BillingManager initialized without a user
        billing_manager = BillingManager(self.license, user=None)
        billing_manager.update_billing_organization_users(self.organization)

        mock_patch.assert_called_once()

        call_kwargs = mock_patch.call_args
        auth_header = call_kwargs[1]["headers"]["Authorization"]
        token = auth_header.replace("Bearer ", "")
        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        # Without a user, there should be no user-related fields
        assert "distinct_id" not in decoded
        assert "organization_role" not in decoded
        assert "original_role" not in decoded

        # No privilege escalation capture should occur
        mock_capture.assert_not_called()


class TestUserUpdateBillingOrganizationUsers(BaseTest):
    """Tests for User.update_billing_organization_users integration with BillingManager"""

    def setUp(self):
        super().setUp()
        self.license = super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="license_id::license_secret",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )

    @patch("posthog.models.user.is_cloud", return_value=True)
    @patch("posthog.models.user.get_cached_instance_license")
    @patch("ee.billing.billing_manager.requests.patch")
    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_user_update_billing_organization_users_passes_self_to_billing_manager(
        self, mock_capture, mock_patch, mock_get_license, mock_is_cloud
    ):
        """
        User.update_billing_organization_users should pass self to BillingManager,
        enabling privilege escalation to work correctly.
        """
        mock_patch.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"text": "ok"}))
        mock_get_license.return_value = self.license

        # Create an owner for the organization
        owner = User.objects.create_and_join(
            organization=self.organization,
            email="owner@example.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )

        # Create a regular member who will call update_billing_organization_users
        member = User.objects.create_and_join(
            organization=self.organization,
            email="member@example.com",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )

        # Reset mocks after user creation (create_and_join also calls update_billing_organization_users)
        mock_patch.reset_mock()
        mock_capture.reset_mock()

        # Call the User method (not BillingManager directly)
        member.update_billing_organization_users(self.organization)

        # Verify the PATCH request was made
        mock_patch.assert_called_once()

        # Extract and decode the JWT token
        call_kwargs = mock_patch.call_args
        auth_header = call_kwargs[1]["headers"]["Authorization"]
        token = auth_header.replace("Bearer ", "")
        decoded = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")

        # Token should have member's distinct_id (the user who called the method)
        assert decoded["distinct_id"] == str(member.distinct_id)
        # organization_role should be the owner's role (privilege escalation)
        assert decoded["organization_role"] == "owner"
        # original_role should be the member's actual role
        assert decoded["original_role"] == "member"

        # Verify privilege escalation was captured
        mock_capture.assert_called_once()
        capture_kwargs = mock_capture.call_args[1]
        assert capture_kwargs["event"] == "$billing_privilege_escalation"
        assert capture_kwargs["properties"]["authorizer_actor_id"] == owner.id
