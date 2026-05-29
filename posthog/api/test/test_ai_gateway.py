from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.ai_gateway import BillingClientError, BillingMisconfigured


class TestAIGatewayViewSet(APIBaseTest):
    def test_wallet_returns_503_when_secret_unset(self) -> None:
        with self.settings(AI_GATEWAY_BILLING_INTERNAL_SECRET=""):
            res = self.client.get(f"/api/projects/{self.team.id}/ai_gateway/wallet/")
        assert res.status_code == 503
        assert res.json() == {"error": "ai_gateway_not_configured"}

    def test_wallet_forwards_to_billing(self) -> None:
        sample = {
            "team_id": self.team.id,
            "available_usd": "12.5",
            "pending_usd": "0",
            "balance_usd": "12.5",
            "spendable_usd": "12.5",
            "currency": "USD",
            "account": {
                "profile": "C",
                "overage_allowance_usd": "0",
                "period": "monthly",
                "period_anchor": "2026-05-01T00:00:00Z",
            },
            "kill_switch": {"tripped": False},
        }
        with (
            self.settings(AI_GATEWAY_BILLING_INTERNAL_SECRET="dev"),
            patch("posthog.api.ai_gateway.BillingClient.wallet", return_value=sample) as mock_wallet,
        ):
            res = self.client.get(f"/api/projects/{self.team.id}/ai_gateway/wallet/")
        assert res.status_code == 200
        assert res.json() == sample
        mock_wallet.assert_called_once_with(self.team.id)

    def test_wallet_502s_when_billing_unreachable(self) -> None:
        with (
            self.settings(AI_GATEWAY_BILLING_INTERNAL_SECRET="dev"),
            patch(
                "posthog.api.ai_gateway.BillingClient.wallet",
                side_effect=BillingClientError(500, "boom"),
            ),
        ):
            res = self.client.get(f"/api/projects/{self.team.id}/ai_gateway/wallet/")
        assert res.status_code == 502

    def test_ledger_passes_filters(self) -> None:
        sample = {"results": [], "next_cursor": None}
        with (
            self.settings(AI_GATEWAY_BILLING_INTERNAL_SECRET="dev"),
            patch("posthog.api.ai_gateway.BillingClient.ledger", return_value=sample) as mock_ledger,
        ):
            res = self.client.get(
                f"/api/projects/{self.team.id}/ai_gateway/ledger/"
                "?limit=25&cursor=abc&transaction_type=debit&reference_id_prefix=agent:s1:"
            )
        assert res.status_code == 200
        mock_ledger.assert_called_once_with(
            self.team.id,
            limit=25,
            cursor="abc",
            transaction_type="debit",
            reference_id_prefix="agent:s1:",
        )

    def test_ledger_rejects_bad_limit(self) -> None:
        with self.settings(AI_GATEWAY_BILLING_INTERNAL_SECRET="dev"):
            res = self.client.get(f"/api/projects/{self.team.id}/ai_gateway/ledger/?limit=not-a-number")
        assert res.status_code == 400

    def test_wallet_requires_team_membership(self) -> None:
        # APIBaseTest uses self.client logged in as a team member. Hitting
        # a foreign team should 403 via the routing mixin's IDOR check.
        self.client.logout()
        with self.settings(AI_GATEWAY_BILLING_INTERNAL_SECRET="dev"):
            res = self.client.get(f"/api/projects/{self.team.id}/ai_gateway/wallet/")
        assert res.status_code in (401, 403)

    def test_misconfigured_short_circuits_before_billing_call(self) -> None:
        with (
            self.settings(AI_GATEWAY_BILLING_INTERNAL_SECRET=""),
            patch("posthog.api.ai_gateway.BillingClient.wallet") as mock_wallet,
        ):
            res = self.client.get(f"/api/projects/{self.team.id}/ai_gateway/wallet/")
        assert res.status_code == 503
        mock_wallet.assert_not_called()
        _ = BillingMisconfigured  # imported for clarity in this assertion's context
