from types import SimpleNamespace

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_CSP_FLAG
from products.customer_analytics.backend.logic.account_member_search import is_account_member_search_enabled
from products.customer_analytics.backend.logic.eligibility import is_person_group_membership_eligible
from products.customer_analytics.backend.logic.usage_spike_notifications import _is_csp_enabled


class TestMembershipEligibility(SimpleTestCase):
    @parameterized.expand([(active, index) for active in [True, False, None] for index in [None, -1, 0, 1, 2, 3, 4, 5]])
    def test_eligibility_fails_closed(self, active: bool | None, index: int | None) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=active):
            assert is_person_group_membership_eligible("organization", index) == (
                bool(active) and index is not None and 0 <= index <= 4
            )

    @parameterized.expand([(True,), (False,)])
    def test_callers_use_the_same_org_gate(self, active: bool) -> None:
        team = SimpleNamespace(organization_id="organization")
        user = SimpleNamespace(is_active=True, is_staff=True, distinct_id="user")
        with patch("posthoganalytics.feature_enabled", return_value=active) as flag:
            assert is_person_group_membership_eligible(team.organization_id, 0) == active
            assert is_account_member_search_enabled(team, user) == active
            assert _is_csp_enabled(SimpleNamespace(team=team)) == active
        with patch(
            "products.customer_analytics.backend.logic.eligibility.is_customer_analytics_active",
            return_value=not active,
        ):
            assert is_person_group_membership_eligible(team.organization_id, 0) == (not active)
            assert is_account_member_search_enabled(team, user) == (not active)
            assert _is_csp_enabled(SimpleNamespace(team=team)) == (not active)
        assert len(flag.call_args_list) == 3
        for call in flag.call_args_list:
            assert call.args == (CUSTOMER_ANALYTICS_CSP_FLAG, "organization")
            assert call.kwargs == {
                "groups": {"organization": "organization"},
                "only_evaluate_locally": False,
                "send_feature_flag_events": False,
            }
