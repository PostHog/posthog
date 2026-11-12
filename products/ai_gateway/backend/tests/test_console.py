import re

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.llm.gateway_internal_client import AIGatewayInternalError, AIGatewayNotConfigured, LedgerEntry, Wallet

from products.ai_gateway.backend.facade.contracts import TeamCreditAdded, TeamCreditRefused


class TestAIGatewayConsole(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def test_the_team_page_links_to_the_wallet_tool(self) -> None:
        content = self.client.get(f"/admin/console/teams/{self.team.pk}/").content.decode()

        assert f"/admin/console/tools/ai-gateway-wallet/?team={self.team.pk}" in content

    @patch("products.ai_gateway.backend.facade.api.add_team_credit")
    def test_a_double_submitted_credit_form_reuses_its_idempotency_key(self, add_credit: MagicMock) -> None:
        add_credit.return_value = TeamCreditAdded(
            entry_id="entry-1", amount_usd="25", balance_usd="25", duplicate=False
        )
        form = self.client.get(f"/admin/console/teams/{self.team.pk}/ai-gateway/add-credit/").content.decode()
        nonce = re.search(r'name="form_nonce" value="([^"]+)"', form)
        assert nonce is not None

        for _ in range(2):
            self.client.post(
                f"/admin/console/teams/{self.team.pk}/ai-gateway/add-credit/",
                {"amount_usd": "25", "reason": "Outage goodwill", "form_nonce": nonce.group(1)},
            )

        nonces = {call.kwargs["form_nonce"] for call in add_credit.call_args_list}
        assert add_credit.call_count == 2
        assert nonces == {nonce.group(1)}

    @parameterized.expand(
        [
            (
                "balance_and_ledger",
                Wallet(
                    team_id=0,
                    known=True,
                    has_ledger=True,
                    balance="9.500000",
                    recent=[LedgerEntry("2026-06-01", "topup", "funding", "prepaid", "10.000000", "ref-1")],
                ),
                ["Balance: $9.500000", "ref-1"],
            ),
            (
                "no_gateway_account",
                Wallet(team_id=0, known=False, has_ledger=True, balance=None, recent=[]),
                ["no gateway account yet", "No ledger entries yet."],
            ),
            ("not_configured", AIGatewayNotConfigured(), ["not configured in this region"]),
            ("gateway_fails", AIGatewayInternalError("boom"), ["The wallet is unavailable: boom"]),
        ]
    )
    def test_the_old_wallet_page_opens_the_wallet_tool(
        self, _name: str, wallet: Wallet | Exception, expected: list[str]
    ) -> None:
        with patch(
            "posthog.llm.gateway_internal_client.get_wallet",
            **({"side_effect": wallet} if isinstance(wallet, Exception) else {"return_value": wallet}),
        ) as get_wallet:
            response = self.client.get(f"/admin/posthog/team/{self.team.pk}/ai-gateway-wallet/", follow=True)

        assert response.redirect_chain == [(f"/admin/console/tools/ai-gateway-wallet/?team={self.team.pk}", 302)]
        get_wallet.assert_called_once_with(self.team.pk)
        content = response.content.decode()
        for text in expected:
            assert text in content

    @patch(
        "products.ai_gateway.backend.facade.api.add_team_credit",
        side_effect=TeamCreditRefused("Failed to add credit: gateway down"),
    )
    def test_a_failed_operation_shows_the_form_again_with_what_staff_typed(self, _add_credit: MagicMock) -> None:
        response = self.client.post(
            f"/admin/console/teams/{self.team.pk}/ai-gateway/add-credit/",
            {"amount_usd": "25", "reason": "Outage goodwill"},
        )

        assert response.status_code == 400
        content = response.content.decode()
        assert "gateway down" in content
        assert "Outage goodwill" in content
