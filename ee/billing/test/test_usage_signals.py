from unittest.mock import patch

from django.test import TestCase

from posthog.models import Organization

from ee.billing.salesforce_enrichment.usage_signals import (
    UsageSignals,
    aggregate_usage_signals_for_orgs,
    fetch_usage_signals_from_groups,
)


class TestUsageSignalsDataClass(TestCase):
    def test_default_values(self):
        signals = UsageSignals()

        assert signals.total_events_7d == 0
        assert signals.total_events_30d == 0
        assert signals.events_avg_daily_7d is None
        assert signals.events_avg_daily_30d is None
        assert signals.products_activated_7d == []
        assert signals.products_activated_30d == []
        assert signals.events_7d_momentum is None
        assert signals.events_30d_momentum is None

    def test_with_values(self):
        signals = UsageSignals(
            total_events_7d=10000,
            events_avg_daily_7d=1428.57,
            products_activated_7d=["analytics", "recordings"],
            events_7d_momentum=15.5,
            total_events_30d=50000,
            events_avg_daily_30d=1666.67,
            products_activated_30d=["analytics", "recordings", "feature_flags"],
            events_30d_momentum=-5.0,
        )

        assert signals.total_events_7d == 10000
        assert signals.events_avg_daily_7d == 1428.57
        assert signals.products_activated_7d == ["analytics", "recordings"]
        assert signals.events_7d_momentum == 15.5
        assert signals.total_events_30d == 50000
        assert signals.events_avg_daily_30d == 1666.67
        assert signals.products_activated_30d == ["analytics", "recordings", "feature_flags"]
        assert signals.events_30d_momentum == -5.0


class TestFetchUsageSignalsFromGroups(TestCase):
    @patch("ee.billing.salesforce_enrichment.usage_signals.query_with_columns")
    def test_returns_parsed_signals(self, mock_query):
        mock_query.return_value = [
            {
                "org_id": "org-uuid-1",
                "events_7d": 10000,
                "events_avg_daily_7d": 1428.57,
                "products_7d": "analytics,recordings",
                "events_30d": 50000,
                "events_avg_daily_30d": 1666.67,
                "products_30d": "analytics,recordings,feature_flags",
                "events_7d_momentum": 15.5,
                "events_30d_momentum": -5.0,
            },
            {
                "org_id": "org-uuid-2",
                "events_7d": 5000,
                "events_avg_daily_7d": 714.29,
                "products_7d": "surveys",
                "events_30d": 20000,
                "events_avg_daily_30d": 666.67,
                "products_30d": "surveys,error_tracking",
                "events_7d_momentum": 25.0,
                "events_30d_momentum": 10.0,
            },
        ]

        result = fetch_usage_signals_from_groups(["org-uuid-1", "org-uuid-2"])

        assert len(result) == 2

        assert result["org-uuid-1"]["total_events_7d"] == 10000
        assert result["org-uuid-1"]["events_avg_daily_7d"] == 1428.57
        assert result["org-uuid-1"]["products_activated_7d"] == ["analytics", "recordings"]
        assert result["org-uuid-1"]["total_events_30d"] == 50000
        assert result["org-uuid-1"]["events_avg_daily_30d"] == 1666.67
        assert result["org-uuid-1"]["products_activated_30d"] == ["analytics", "recordings", "feature_flags"]
        assert result["org-uuid-1"]["events_7d_momentum"] == 15.5
        assert result["org-uuid-1"]["events_30d_momentum"] == -5.0

        assert result["org-uuid-2"]["total_events_7d"] == 5000
        assert result["org-uuid-2"]["products_activated_7d"] == ["surveys"]

    @patch("ee.billing.salesforce_enrichment.usage_signals.query_with_columns")
    def test_empty_org_ids_returns_empty_dict(self, mock_query):
        result = fetch_usage_signals_from_groups([])

        assert result == {}
        mock_query.assert_not_called()

    @patch("ee.billing.salesforce_enrichment.usage_signals.query_with_columns")
    def test_no_results_returns_empty_dict(self, mock_query):
        mock_query.return_value = []

        result = fetch_usage_signals_from_groups(["org-uuid-1"])

        assert result == {}

    @patch("ee.billing.salesforce_enrichment.usage_signals.query_with_columns")
    def test_handles_null_values(self, mock_query):
        mock_query.return_value = [
            {
                "org_id": "org-uuid-1",
                "events_7d": None,
                "events_avg_daily_7d": None,
                "products_7d": "",
                "events_30d": None,
                "events_avg_daily_30d": None,
                "products_30d": None,
                "events_7d_momentum": None,
                "events_30d_momentum": None,
            },
        ]

        result = fetch_usage_signals_from_groups(["org-uuid-1"])

        assert result["org-uuid-1"]["total_events_7d"] == 0
        assert result["org-uuid-1"]["events_avg_daily_7d"] is None
        assert result["org-uuid-1"]["products_activated_7d"] == []
        assert result["org-uuid-1"]["total_events_30d"] == 0
        assert result["org-uuid-1"]["events_avg_daily_30d"] is None
        assert result["org-uuid-1"]["products_activated_30d"] == []
        assert result["org-uuid-1"]["events_7d_momentum"] is None
        assert result["org-uuid-1"]["events_30d_momentum"] is None


class TestAggregateUsageSignalsForOrgs(TestCase):
    org: Organization

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Test Org")

    def test_empty_org_ids_returns_empty_dict(self):
        result = aggregate_usage_signals_for_orgs([])
        assert result == {}

    @patch("ee.billing.salesforce_enrichment.usage_signals.fetch_usage_signals_from_groups")
    def test_returns_usage_signals_for_orgs(self, mock_fetch):
        org_id = str(self.org.id)
        mock_fetch.return_value = {
            org_id: {
                "total_events_7d": 10000,
                "events_avg_daily_7d": 1428.57,
                "products_activated_7d": ["analytics", "recordings"],
                "events_7d_momentum": 15.5,
                "total_events_30d": 50000,
                "events_avg_daily_30d": 1666.67,
                "products_activated_30d": ["analytics", "recordings", "feature_flags"],
                "events_30d_momentum": -5.0,
            }
        }

        result = aggregate_usage_signals_for_orgs([org_id])

        assert org_id in result
        signals = result[org_id]
        assert signals.total_events_7d == 10000
        assert signals.events_avg_daily_7d == 1428.57
        assert signals.products_activated_7d == ["analytics", "recordings"]
        assert signals.events_7d_momentum == 15.5
        assert signals.total_events_30d == 50000
        assert signals.events_avg_daily_30d == 1666.67
        assert signals.products_activated_30d == ["analytics", "recordings", "feature_flags"]
        assert signals.events_30d_momentum == -5.0

    @patch("ee.billing.salesforce_enrichment.usage_signals.fetch_usage_signals_from_groups")
    def test_org_with_no_signals_returns_default(self, mock_fetch):
        org_id = str(self.org.id)
        mock_fetch.return_value = {}  # No signals found for org

        result = aggregate_usage_signals_for_orgs([org_id])

        assert org_id in result
        signals = result[org_id]
        assert signals.total_events_7d == 0
        assert signals.events_avg_daily_7d is None
        assert signals.products_activated_7d == []
        assert signals.events_7d_momentum is None

    @patch("ee.billing.salesforce_enrichment.usage_signals.fetch_usage_signals_from_groups")
    def test_multiple_orgs(self, mock_fetch):
        org2 = Organization.objects.create(name="Test Org 2")
        org_id1 = str(self.org.id)
        org_id2 = str(org2.id)

        mock_fetch.return_value = {
            org_id1: {
                "total_events_7d": 10000,
                "events_avg_daily_7d": 1428.57,
                "products_activated_7d": ["analytics"],
                "events_7d_momentum": 15.5,
                "total_events_30d": 50000,
                "events_avg_daily_30d": 1666.67,
                "products_activated_30d": ["analytics"],
                "events_30d_momentum": -5.0,
            },
            org_id2: {
                "total_events_7d": 5000,
                "events_avg_daily_7d": 714.29,
                "products_activated_7d": ["surveys"],
                "events_7d_momentum": 25.0,
                "total_events_30d": 20000,
                "events_avg_daily_30d": 666.67,
                "products_activated_30d": ["surveys"],
                "events_30d_momentum": 10.0,
            },
        }

        result = aggregate_usage_signals_for_orgs([org_id1, org_id2])

        assert len(result) == 2
        assert result[org_id1].total_events_7d == 10000
        assert result[org_id2].total_events_7d == 5000
