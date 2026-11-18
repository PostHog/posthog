import datetime
from typing import cast

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import jwt
import requests
from parameterized import parameterized

from posthog.cloud_utils import TEST_clear_instance_license_cache
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.tasks.sync_billing import TransientBillingSyncError, sync_members_to_billing

from ee.billing.billing_manager import BillingServiceResponseError
from ee.models.license import License, LicenseManager


def _response(status_code: int) -> MagicMock:
    return MagicMock(status_code=status_code, json=MagicMock(return_value={}), text="")


class TestSyncMembersToBilling(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cloud_patcher = patch("posthog.cloud_utils.is_cloud", return_value=True)
        cloud_patcher.start()
        self.addCleanup(cloud_patcher.stop)
        http_patcher = patch("ee.billing.billing_manager.http_session.patch")
        self.mock_patch = http_patcher.start()
        self.addCleanup(http_patcher.stop)
        TEST_clear_instance_license_cache()
        self.addCleanup(TEST_clear_instance_license_cache)
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="license_id::license_secret",
            plan="enterprise",
            valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
        )

    def _join(self, email: str, level: OrganizationMembership.Level, is_active: bool = True) -> User:
        user = User.objects.create_and_join(organization=self.organization, email=email, password=None, level=level)
        if not is_active:
            User.objects.filter(id=user.id).update(is_active=False)
        return user

    @parameterized.expand(
        [
            ("server_error", _response(503)),
            ("request_timeout", _response(408)),
            ("rate_limited", _response(429)),
            ("connection_error", requests.ConnectionError("proxy error")),
            ("timeout", requests.ReadTimeout("read timed out")),
        ]
    )
    def test_retries_a_transient_failure_until_billing_takes_the_sync(
        self, _name: str, first_attempt: MagicMock | Exception
    ) -> None:
        self._join("owner@example.com", OrganizationMembership.Level.OWNER)
        self.mock_patch.side_effect = [first_attempt, _response(200)]

        # throw=False lets apply() run the retry in place, as a worker would after the backoff.
        result = sync_members_to_billing.apply(args=[str(self.organization.id)], throw=False)

        assert result.successful()
        assert self.mock_patch.call_count == 2
        assert self.mock_patch.call_args.kwargs["json"]["org_customer_email"] == "owner@example.com"

    def test_raises_the_failure_on_the_last_retry(self) -> None:
        self._join("owner@example.com", OrganizationMembership.Level.OWNER)
        self.mock_patch.return_value = _response(503)

        with pytest.raises(TransientBillingSyncError):
            sync_members_to_billing.apply(args=[str(self.organization.id)], retries=sync_members_to_billing.max_retries)

        self.mock_patch.assert_called_once()

    def test_does_not_retry_a_client_error(self) -> None:
        self._join("owner@example.com", OrganizationMembership.Level.OWNER)
        self.mock_patch.return_value = _response(400)

        with pytest.raises(BillingServiceResponseError):
            sync_members_to_billing.apply(args=[str(self.organization.id)])

        self.mock_patch.assert_called_once()

    @parameterized.expand(
        [
            (
                "admin_without_owner",
                [("admin@example.com", OrganizationMembership.Level.ADMIN, True)],
                "admin@example.com",
            ),
            (
                "active_admin_over_deactivated_owner",
                [
                    ("owner@example.com", OrganizationMembership.Level.OWNER, False),
                    ("admin@example.com", OrganizationMembership.Level.ADMIN, True),
                ],
                "admin@example.com",
            ),
            (
                "owner_over_newer_admin",
                [
                    ("owner@example.com", OrganizationMembership.Level.OWNER, True),
                    ("admin@example.com", OrganizationMembership.Level.ADMIN, True),
                ],
                "owner@example.com",
            ),
        ]
    )
    def test_authorizes_as_the_chosen_member_and_sends_their_email(
        self, _name: str, members: list[tuple[str, OrganizationMembership.Level, bool]], expected_email: str
    ) -> None:
        for email, level, is_active in members:
            self._join(email, level, is_active)
        self.mock_patch.return_value = _response(200)

        sync_members_to_billing(str(self.organization.id))

        self.mock_patch.assert_called_once()
        assert self.mock_patch.call_args.kwargs["json"]["org_customer_email"] == expected_email
        token = self.mock_patch.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(token, "license_secret", algorithms=["HS256"], audience="posthog:license-key")
        assert claims["email"] == expected_email

    def test_skips_an_organization_without_owner_or_admin(self) -> None:
        sync_members_to_billing(str(self.organization.id))

        self.mock_patch.assert_not_called()
