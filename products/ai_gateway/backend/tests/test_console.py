import re
from datetime import UTC, date, datetime

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.llm.gateway_internal_client import (
    AIGatewayInternalError,
    AIGatewayNotConfigured,
    LedgerEntry,
    OrgProductSpend,
    OrgSpend,
    Wallet,
)
from posthog.models.team.team import Team

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

    def test_the_organization_page_counts_enrolled_teams_and_links_to_the_wallet(self) -> None:
        self.team.llm_gateway_enabled_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.team.save()
        revoked = Team.objects.create(organization=self.organization, name="Revoked")
        Team.objects.filter(pk=revoked.pk).update(
            llm_gateway_enabled_at=datetime(2026, 1, 1, tzinfo=UTC),
            llm_gateway_revoked_at=datetime(2026, 2, 1, tzinfo=UTC),
        )

        content = self.client.get(f"/admin/console/organizations/{self.organization.pk}/").content.decode()

        assert "1 of 2 teams enrolled" in content
        assert f"/admin/console/tools/ai-gateway-wallet/?organization={self.organization.pk}" in content

    @parameterized.expand(
        [
            ("no_period", "", date(2026, 2, 14), date(2026, 3, 16), "Feb 14, 2026 to Mar 15, 2026"),
            ("last_30_days", "last-30-days", date(2026, 2, 14), date(2026, 3, 16), "Feb 14, 2026 to Mar 15, 2026"),
            ("this_month", "this-month", date(2026, 3, 1), date(2026, 3, 16), "Mar 1, 2026 to Mar 15, 2026"),
            ("last_month", "last-month", date(2026, 2, 1), date(2026, 3, 1), "Feb 1, 2026 to Feb 28, 2026"),
            ("unknown_period", "all-time", date(2026, 2, 14), date(2026, 3, 16), "Feb 14, 2026 to Mar 15, 2026"),
        ]
    )
    @time_machine.travel("2026-03-15T12:00:00Z", tick=False)
    def test_the_organization_wallet_shows_balance_and_spend_by_product(
        self, _name: str, period: str, start: date, end: date, days: str
    ) -> None:
        org_id = str(self.organization.pk)
        spend = OrgSpend(
            balance_usd="-1234.500000",
            spend_usd="80.250000",
            free_usd="5.000000",
            products=[
                OrgProductSpend(product="posthog_code", spend_usd="80.000000", free_usd="5.000000"),
                OrgProductSpend(product="unattributed", spend_usd="0.250000", free_usd="0.000000"),
                OrgProductSpend(product="signals", spend_usd="0.000000", free_usd="0.000000"),
            ],
            truncated=True,
        )
        report = [
            {"keys": {"product": "posthog_code"}, "list_usd": "85.000000"},
            {"keys": {"product": None}, "list_usd": "0.001000"},
        ]
        with (
            patch("posthog.llm.gateway_internal_client.get_org_spend", return_value=spend) as get_org_spend,
            patch("posthog.llm.gateway_internal_client.get_usage_report_rows", return_value=report) as get_report,
        ):
            content = self.client.get(
                "/admin/console/tools/ai-gateway-wallet/", {"organization": org_id, "period": period}
            ).content.decode()

        get_org_spend.assert_called_once_with(org_id, start, end)
        params = get_report.call_args.args[0]
        assert (params["group_by"], params["billed_org_id"]) == ("product", org_id)
        assert (params["from"], params["to"]) == (f"{start}T00:00:00+00:00", f"{end}T00:00:00+00:00")
        for text in [
            self.organization.name,
            days,
            "-$1,234.50",
            "$80.25",
            # posthog_code: charged, free allocation, list cost.
            "$80.00",
            "$5.00",
            "$85.00",
            # The report's null product is the spend route's "unattributed".
            "&lt;$0.01",
            # A product the report has no row for.
            "Not reported",
            "50 products with the most spend",
        ]:
            assert text in content, text

    @parameterized.expand(
        [
            ("not_configured", AIGatewayNotConfigured(), None, "not configured in this region"),
            ("spend_read_fails", AIGatewayInternalError("boom"), None, "The wallet is unavailable: boom"),
            ("report_read_fails", None, AIGatewayInternalError("slow"), "The wallet is unavailable: slow"),
            ("report_amount_is_not_a_number", None, [{"keys": {"product": "x"}, "list_usd": None}], "list_usd"),
        ]
    )
    def test_the_organization_wallet_says_why_it_is_unavailable(
        self, _name: str, spend_error: Exception | None, report: Exception | list | None, expected: str
    ) -> None:
        spend = OrgSpend(balance_usd="0", spend_usd="0", free_usd="0", products=[], truncated=False)
        with (
            patch(
                "posthog.llm.gateway_internal_client.get_org_spend",
                **({"side_effect": spend_error} if spend_error else {"return_value": spend}),
            ),
            patch(
                "posthog.llm.gateway_internal_client.get_usage_report_rows",
                **({"side_effect": report} if isinstance(report, Exception) else {"return_value": report or []}),
            ),
        ):
            response = self.client.get(
                "/admin/console/tools/ai-gateway-wallet/", {"organization": str(self.organization.pk)}
            )

        assert response.status_code == 200
        content = response.content.decode()
        assert expected in content
        assert "Back to the organization" in content

    @parameterized.expand(
        [
            ("no_organization", {}, "Enter an organization ID"),
            ("unknown_organization", {"organization": "0190b3a1-1111-7000-8000-000000000001"}, "No organization has"),
            ("malformed_organization", {"organization": "not-a-uuid"}, "No organization has"),
            ("unknown_team", {"team": "999999999"}, "No team has this ID."),
        ]
    )
    def test_the_wallet_tool_asks_for_a_record_it_can_find(self, _name: str, query: dict, expected: str) -> None:
        response = self.client.get("/admin/console/tools/ai-gateway-wallet/", query)

        assert response.status_code == 200
        assert expected in response.content.decode()

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
