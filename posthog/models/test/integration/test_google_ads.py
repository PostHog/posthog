"""Tests for the Google Ads integration."""

from typing import Optional

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from parameterized import parameterized

from posthog.models.integration import GoogleAdsAccountWalkError, GoogleAdsIntegration, Integration


class TestGoogleAdsIntegrationModel(BaseTest):
    def _integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="google-ads",
            config={},
            sensitive_config={"access_token": "token"},
            integration_id="google_ads_test",
        )

    @staticmethod
    def _customer_client(
        customer_id: str,
        name: str,
        level: Optional[str] = None,
        manager: bool = False,
        status: Optional[str] = "ENABLED",
        test_account: bool = False,
    ) -> dict:
        client: dict = {"clientCustomer": f"customers/{customer_id}", "descriptiveName": name}
        # Google's REST responses omit proto3 defaults, so level 0, manager=false, testAccount=false and
        # an unset status are absent from the row.
        if status is not None:
            client["status"] = status
        if level is not None:
            client["level"] = level
        if manager:
            client["manager"] = True
        if test_account:
            client["testAccount"] = True
        return {"customerClient": client}

    @override_settings(GOOGLE_ADS_DEVELOPER_TOKEN="dev_token")
    @patch("posthog.models.integration.google_ads.requests.request")
    def test_accessible_accounts_reads_every_search_stream_chunk(self, mock_request):
        accessible = MagicMock(status_code=200)
        accessible.json.return_value = {"resourceNames": ["customers/6501924158"]}
        # searchStream's REST body is an array of batches; a large hierarchy spans several.
        stream = MagicMock(status_code=200)
        stream.json.return_value = [
            {"results": [self._customer_client("6501924158", "Acme Corp", manager=True)]},
            {"results": [self._customer_client("1234567890", "Client One", level="1")]},
        ]
        mock_request.side_effect = [accessible, stream]

        accounts = GoogleAdsIntegration(self._integration()).list_google_ads_accessible_accounts()

        assert [account["id"] for account in accounts] == ["6501924158", "1234567890"]
        assert accounts[0]["manager"] is True
        assert accounts[1]["parent_id"] == "6501924158"

    @override_settings(GOOGLE_ADS_DEVELOPER_TOKEN="dev_token")
    @patch("posthog.models.integration.google_ads.requests.request")
    def test_accessible_accounts_dedupes_an_account_reachable_from_two_roots(self, mock_request):
        # A user with direct access to both a manager and one of its clients gets both in
        # `resourceNames`, so the client is walked twice: once as a root (level absent, i.e. 0) and once
        # under the manager (level "1"). Those two levels must be compared as numbers — comparing the raw
        # values raises TypeError (None vs "1") and 500s the picker.
        accessible = MagicMock(status_code=200)
        accessible.json.return_value = {"resourceNames": ["customers/1234567890", "customers/6501924158"]}
        client_walk = MagicMock(status_code=200)
        client_walk.json.return_value = [{"results": [self._customer_client("1234567890", "Client One")]}]
        manager_walk = MagicMock(status_code=200)
        manager_walk.json.return_value = [
            {
                "results": [
                    self._customer_client("6501924158", "Acme Corp", manager=True),
                    self._customer_client("1234567890", "Client One", level="1"),
                ]
            }
        ]
        mock_request.side_effect = [accessible, client_walk, manager_walk]

        accounts = GoogleAdsIntegration(self._integration()).list_google_ads_accessible_accounts()

        # The client is kept once, at its shallowest sighting: reachable directly, so it needs no manager
        # to log in as.
        assert [account["id"] for account in accounts] == ["1234567890", "6501924158"]
        assert accounts[0]["level"] is None
        assert accounts[0]["parent_id"] == "1234567890"

    @override_settings(GOOGLE_ADS_DEVELOPER_TOKEN="dev_token")
    @patch("posthog.models.integration.google_ads.requests.request")
    def test_accessible_accounts_keeps_live_sighting_when_shallower_root_is_dead(self, mock_request):
        # The same client is reachable enabled under a manager (level "1") and directly as a canceled root
        # (level 0). The enabled path is walked first and kept; the canceled shallower root must not evict
        # it, otherwise the account vanishes from the picker even though Google returned an enabled path.
        accessible = MagicMock(status_code=200)
        accessible.json.return_value = {"resourceNames": ["customers/6501924158", "customers/1234567890"]}
        manager_walk = MagicMock(status_code=200)
        manager_walk.json.return_value = [
            {
                "results": [
                    self._customer_client("6501924158", "Acme Corp", manager=True),
                    self._customer_client("1234567890", "Client One", level="1"),
                ]
            }
        ]
        dead_root_walk = MagicMock(status_code=200)
        dead_root_walk.json.return_value = [
            {"results": [self._customer_client("1234567890", "Client One", status="CANCELED")]}
        ]
        mock_request.side_effect = [accessible, manager_walk, dead_root_walk]

        accounts = GoogleAdsIntegration(self._integration()).list_google_ads_accessible_accounts()

        client = next(account for account in accounts if account["id"] == "1234567890")
        assert client["level"] == "1"
        assert client["parent_id"] == "6501924158"

    @override_settings(GOOGLE_ADS_DEVELOPER_TOKEN="dev_token")
    @patch("posthog.models.integration.google_ads.requests.request")
    def test_accessible_accounts_empty_when_login_has_no_accessible_customers(self, mock_request):
        # A Google login with no accessible Ads accounts gets a 200 with an empty body, so `resourceNames`
        # is absent rather than an empty list — this must yield no accounts, not raise KeyError.
        accessible = MagicMock(status_code=200)
        accessible.json.return_value = {}
        mock_request.return_value = accessible

        accounts = GoogleAdsIntegration(self._integration()).list_google_ads_accessible_accounts()

        assert accounts == []

    @override_settings(GOOGLE_ADS_DEVELOPER_TOKEN="dev_token")
    @patch("tenacity.nap.time.sleep")
    @patch("posthog.models.integration.google_ads.requests.request")
    def test_accessible_accounts_rides_out_one_transient_read_timeout(self, mock_request, mock_sleep):
        # The walk is a chain of sequential requests; a single timed-out request used to fail the whole
        # walk. It must instead be retried once and succeed.
        accessible = MagicMock(status_code=200)
        accessible.json.return_value = {"resourceNames": ["customers/6501924158"]}
        stream = MagicMock(status_code=200)
        stream.json.return_value = [{"results": [self._customer_client("1234567890", "Client One", level="1")]}]
        mock_request.side_effect = [accessible, requests.exceptions.ReadTimeout("read timed out"), stream]

        accounts = GoogleAdsIntegration(self._integration()).list_google_ads_accessible_accounts()

        assert [account["id"] for account in accounts] == ["1234567890"]

    @override_settings(GOOGLE_ADS_DEVELOPER_TOKEN="dev_token")
    @patch("tenacity.nap.time.sleep")
    @patch("posthog.models.integration.google_ads.requests.request")
    def test_accessible_accounts_raises_after_repeated_read_timeouts(self, mock_request, mock_sleep):
        # Retries must be bounded: a persistently unreachable endpoint should still fail rather than
        # retry forever or get silently swallowed.
        mock_request.side_effect = requests.exceptions.ReadTimeout("read timed out")

        with pytest.raises(requests.exceptions.ReadTimeout):
            GoogleAdsIntegration(self._integration()).list_google_ads_accessible_accounts()

        assert mock_request.call_count == 3

    @parameterized.expand(
        [
            # A row with an unset status arrives with no `status` key at all, and a suspended account can
            # be reactivated. Only a canceled or closed account is dead, so only those two are dropped.
            ("status_absent", None, True),
            ("enabled", "ENABLED", True),
            ("suspended", "SUSPENDED", True),
            ("unknown_to_us", "SOMETHING_NEW", True),
            ("canceled", "CANCELED", False),
            ("closed", "CLOSED", False),
        ]
    )
    @override_settings(GOOGLE_ADS_DEVELOPER_TOKEN="dev_token")
    @patch("posthog.models.integration.google_ads.requests.request")
    def test_accessible_accounts_only_drops_dead_statuses(self, _name, status, expected_in_picker, mock_request):
        accessible = MagicMock(status_code=200)
        accessible.json.return_value = {"resourceNames": ["customers/1234567890"]}
        stream = MagicMock(status_code=200)
        stream.json.return_value = [{"results": [self._customer_client("1234567890", "Client One", status=status)]}]
        mock_request.side_effect = [accessible, stream]

        accounts = GoogleAdsIntegration(self._integration()).list_google_ads_accessible_accounts()

        assert bool(accounts) is expected_in_picker

    @override_settings(GOOGLE_ADS_DEVELOPER_TOKEN="dev_token")
    @patch("posthog.models.integration.google_ads.requests.request")
    def test_accessible_accounts_labels_a_test_account(self, mock_request):
        # Without this flag a test account looks the same as a production one.
        accessible = MagicMock(status_code=200)
        accessible.json.return_value = {"resourceNames": ["customers/6501924158"]}
        stream = MagicMock(status_code=200)
        stream.json.return_value = [
            {
                "results": [
                    self._customer_client("6501924158", "Acme Corp", manager=True),
                    self._customer_client("1234567890", "Acme Test", level="1", test_account=True),
                ]
            }
        ]
        mock_request.side_effect = [accessible, stream]

        accounts = GoogleAdsIntegration(self._integration()).list_google_ads_accessible_accounts()

        assert [account["test_account"] for account in accounts] == [False, True]

    @override_settings(GOOGLE_ADS_DEVELOPER_TOKEN="dev_token")
    @patch("posthog.models.integration.google_ads.requests.request")
    def test_accessible_accounts_raises_when_a_hierarchy_walk_fails(self, mock_request):
        # A non-200 part-way through the walk used to return the accounts collected so far, so the picker
        # showed a short list and no message. It must fail loudly instead.
        accessible = MagicMock(status_code=200)
        accessible.json.return_value = {"resourceNames": ["customers/6501924158", "customers/1234567890"]}
        manager_walk = MagicMock(status_code=200)
        manager_walk.json.return_value = [{"results": [self._customer_client("6501924158", "Acme Corp", manager=True)]}]
        failed_walk = MagicMock(status_code=500, text="internal error")
        mock_request.side_effect = [accessible, manager_walk, failed_walk]

        with pytest.raises(GoogleAdsAccountWalkError):
            GoogleAdsIntegration(self._integration()).list_google_ads_accessible_accounts()
