from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import ColumnConfiguration
from posthog.models.team import Team

from products.customer_analytics.backend.logic.accounts_saved_view_usage import (
    ACCOUNTS_COLUMN_CONFIG_CONTEXT_KEY,
    capture_accounts_saved_view_unsupported_column_usage,
    classify_account_column_expression,
)


class TestClassifyAccountColumnExpression(SimpleTestCase):
    @parameterized.expand(
        [
            ("account_field", "created_at", None),
            ("tags", "accounts.tags.names AS tag_names", None),
            ("notes", "accounts.notebooks.count AS notebook_count", None),
            (
                "custom_property",
                "accounts.custom_properties.values.`11111111-2222-3333-4444-555555555555` AS cp_1",
                None,
            ),
            (
                "custom_property_metric",
                "toFloatOrNull(accounts.custom_properties.values.`11111111-2222-3333-4444-555555555555`)",
                None,
            ),
            (
                "relationship",
                "accounts.relationships.values.`11111111-2222-3333-4444-555555555555` AS rel_1",
                None,
            ),
            ("warehouse_join", "accounts.salesforce.account_tier AS account_tier", "external_join"),
            ("arbitrary_lazy_join", "accounts.enrichment.score AS score", "external_join"),
            ("custom_sql", "concat(name, ' (', external_id, ')') AS display_name", "custom_sql"),
        ]
    )
    def test_classifies_saved_column_sources(self, _name: str, expression: str, expected: str | None) -> None:
        assert classify_account_column_expression(expression) == expected


class TestCaptureAccountsSavedViewUnsupportedColumnUsage(BaseTest):
    def test_reports_unsupported_usage_for_the_team_and_accounts_scope(self) -> None:
        ColumnConfiguration.objects.create(
            team=self.team,
            context_key=ACCOUNTS_COLUMN_CONFIG_CONTEXT_KEY,
            columns=[
                "name",
                "accounts.tags.names AS tag_names",
                "accounts.relationships.values.`11111111-2222-3333-4444-555555555555` AS rel_1",
            ],
        )
        ColumnConfiguration.objects.create(
            team=self.team,
            context_key=ACCOUNTS_COLUMN_CONFIG_CONTEXT_KEY,
            name="Custom expression",
            columns=["concat(name, external_id) AS display_name"],
        )
        ColumnConfiguration.objects.create(
            team=self.team,
            context_key=ACCOUNTS_COLUMN_CONFIG_CONTEXT_KEY,
            name="Warehouse",
            columns=["accounts.salesforce.account_tier AS account_tier"],
            properties={
                "tiles": [
                    {
                        "metric": {
                            "type": "sum",
                            "columnExpression": "accounts.salesforce.annual_revenue",
                        }
                    }
                ]
            },
        )
        ColumnConfiguration.objects.create(
            team=self.team,
            context_key="another_context",
            columns=["accounts.salesforce.should_not_count AS should_not_count"],
        )
        other_team = Team.objects.create(organization=self.organization)
        ColumnConfiguration.objects.create(
            team=other_team,
            context_key=ACCOUNTS_COLUMN_CONFIG_CONTEXT_KEY,
            columns=["accounts.salesforce.should_not_count AS should_not_count"],
        )

        with patch(
            "products.customer_analytics.backend.logic.accounts_saved_view_usage.report_team_action"
        ) as report_team_action:
            capture_accounts_saved_view_unsupported_column_usage(self.team)

        report_team_action.assert_called_once_with(
            self.team,
            "customer analytics accounts unsupported saved view detected",
            {
                "configuration_count": 3,
                "custom_sql_configuration_count": 1,
                "external_join_configuration_count": 1,
                "custom_sql_column_count": 1,
                "external_join_column_count": 2,
            },
        )

    def test_does_not_report_when_every_saved_view_is_postgres_backed(self) -> None:
        ColumnConfiguration.objects.create(
            team=self.team,
            context_key=ACCOUNTS_COLUMN_CONFIG_CONTEXT_KEY,
            columns=["name", "accounts.notebooks.count AS notebook_count"],
        )

        with patch(
            "products.customer_analytics.backend.logic.accounts_saved_view_usage.report_team_action"
        ) as report_team_action:
            capture_accounts_saved_view_unsupported_column_usage(self.team)

        report_team_action.assert_not_called()
