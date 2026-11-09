from datetime import timedelta
from decimal import Decimal

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.llm.gateway_internal_client import AIGatewayInternalError, CreditResult
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team

from products.ai_gateway.backend.facade import api
from products.ai_gateway.backend.facade.contracts import TeamCreditRefused
from products.ai_gateway.backend.facade.enums import TeamAccessAction

_ADD_CREDIT = "posthog.llm.gateway_internal_client.add_credit"
_REFRESH_POLICY = "products.ai_gateway.backend.logic.update_team_llm_gateway_policy_cache"


class TestTeamAccess(BaseTest):
    @parameterized.expand(
        [
            ("enable", TeamAccessAction.ENABLE, "llm_gateway_enabled_at", False, True, True),
            ("enable_already_enabled", TeamAccessAction.ENABLE, "llm_gateway_enabled_at", True, True, False),
            ("unenable", TeamAccessAction.UNENABLE, "llm_gateway_enabled_at", True, False, True),
            ("revoke", TeamAccessAction.REVOKE, "llm_gateway_revoked_at", False, True, True),
            ("revoke_already_revoked", TeamAccessAction.REVOKE, "llm_gateway_revoked_at", True, True, False),
            ("unrevoke", TeamAccessAction.UNREVOKE, "llm_gateway_revoked_at", True, False, True),
            ("unrevoke_not_revoked", TeamAccessAction.UNREVOKE, "llm_gateway_revoked_at", False, False, False),
        ]
    )
    def test_change_team_access(
        self, _name: str, action: TeamAccessAction, field: str, preset: bool, expect_set: bool, expect_changed: bool
    ) -> None:
        original = timezone.now() - timedelta(days=1)
        if preset:
            setattr(self.team, field, original)
            self.team.save()

        with patch(_REFRESH_POLICY) as refresh_policy:
            change = api.change_team_access(self.team.pk, action)

        self.team.refresh_from_db()
        value = getattr(self.team, field)
        assert (value is not None) == expect_set
        if preset and expect_set:
            assert value == original
        assert change.changed == expect_changed
        # The refresh runs on a no-op too, where team.save() and its signal are skipped.
        assert refresh_policy.call_count == 1


class TestTeamCredit(BaseTest):
    def _credit(self, amount: str = "5", reason: str = "goodwill", nonce: str = "n1", impersonated: bool = False):
        return api.add_team_credit(
            self.team.pk, Decimal(amount), reason, form_nonce=nonce, actor=self.user, was_impersonated=impersonated
        )

    def _result(self, entry_id: str = "e1", duplicate: bool = False, team: Team | None = None) -> CreditResult:
        team_id = (team or self.team).pk
        return CreditResult(team_id=team_id, entry_id=entry_id, amount_usd="5", balance_usd="15", duplicate=duplicate)

    def test_idempotency_key_binds_the_nonce_amount_and_reason(self) -> None:
        with patch(_ADD_CREDIT, return_value=self._result()) as add_credit:
            self._credit(amount="10")
            self._credit(amount="10")
            self._credit(amount="20")

        keys = [call.args[3] for call in add_credit.call_args_list]
        assert keys[0] == keys[1]
        assert keys[2] != keys[0]

    @parameterized.expand(
        [
            ("zero", "0", "x"),
            ("negative", "-5", "x"),
            ("nan", "NaN", "x"),
            ("infinity", "Infinity", "x"),
            ("over_cap", "1000001", "x"),
            ("blank_reason", "5", "  "),
        ]
    )
    def test_rejected_inputs_never_reach_the_gateway(self, _name: str, amount: str, reason: str) -> None:
        with patch(_ADD_CREDIT) as add_credit, self.assertRaises(TeamCreditRefused):
            self._credit(amount=amount, reason=reason)

        add_credit.assert_not_called()

    def test_gateway_failure_is_refused_without_an_audit_row(self) -> None:
        with (
            patch(_ADD_CREDIT, side_effect=AIGatewayInternalError("down")),
            self.assertRaisesRegex(TeamCreditRefused, "down"),
        ):
            self._credit()

        assert not ActivityLog.objects.filter(scope="AIGatewayCredit", team_id=self.team.pk).exists()

    @parameterized.expand([("new_credit", False, False), ("replay_backfills_lost_audit", True, True)])
    def test_credit_records_one_audit_row_with_the_actor(self, _name: str, duplicate: bool, impersonated: bool) -> None:
        with patch(_ADD_CREDIT, return_value=self._result(duplicate=duplicate)):
            self._credit(impersonated=impersonated)
            self._credit(impersonated=impersonated)

        entry = ActivityLog.objects.get(scope="AIGatewayCredit", team_id=self.team.pk)
        assert entry.item_id == "e1"
        assert entry.user == self.user
        assert entry.was_impersonated is impersonated
        assert (entry.detail or {}).get("context", {}).get("reason") == "goodwill"
        top_ups = api.recent_team_credits(self.team.pk, limit=3)
        assert [(top_up.amount_usd, top_up.actor_email) for top_up in top_ups] == [("5", self.user.email)]

    def test_audit_dedup_is_scoped_to_the_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        with patch(_ADD_CREDIT, return_value=self._result(entry_id="shared")):
            self._credit()
            api.add_team_credit(
                other_team.pk, Decimal("5"), "goodwill", form_nonce="n1", actor=self.user, was_impersonated=False
            )

        assert ActivityLog.objects.filter(scope="AIGatewayCredit", item_id="shared").count() == 2

    @patch("products.ai_gateway.backend.logic.log_activity", side_effect=Exception("boom"))
    def test_audit_failure_after_the_money_moved_still_returns_the_credit(self, _log_activity: MagicMock) -> None:
        with patch(_ADD_CREDIT, return_value=self._result()):
            result = self._credit()

        assert result.entry_id == "e1"
