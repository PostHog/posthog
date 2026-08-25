import pytest

from posthog.management.commands.seed_ai_gateway_budgets import routed_products


class TestRoutedProducts:
    @pytest.mark.parametrize(
        "products_csv,expected",
        [
            ("signals_scout,signals_research", ["signals_research", "signals_scout"]),
            # A skill-qualified entry narrows which runs route, but the budget key is
            # the product node, which carries no skill. Keeping the qualifier would
            # seed "signals_scout:web-analytics", a string no request ever produces.
            ("signals_scout:web-analytics", ["signals_scout"]),
            # Qualified and bare entries for one product are one budget, not two.
            ("signals_scout:web-analytics,signals_scout", ["signals_scout"]),
            (" signals_scout , signals_research ", ["signals_research", "signals_scout"]),
            ("", []),
            (",,", []),
        ],
    )
    def test_derives_budgetable_products(self, products_csv, expected):
        assert routed_products(products_csv) == expected
