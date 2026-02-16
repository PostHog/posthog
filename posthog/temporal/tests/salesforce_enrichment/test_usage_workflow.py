import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase

from posthog.temporal.salesforce_enrichment.usage_workflow import (
    SalesforceOrgMapping,
    SalesforceUsageEnrichmentWorkflow,
    SalesforceUsageUpdate,
    UsageEnrichmentInputs,
    cache_org_mappings_activity,
    prepare_salesforce_update_record,
    update_salesforce_usage_activity,
)

from ee.billing.salesforce_enrichment.usage_signals import UsageSignals


async def mock_to_thread(fn, *args, **kwargs):
    """Mock asyncio.to_thread that returns an awaitable."""
    return fn(*args, **kwargs)


class TestSalesforceOrgMapping(TestCase):
    def test_create_mapping(self):
        mapping = SalesforceOrgMapping(
            salesforce_account_id="001ABC123",
            posthog_org_id="550e8400-e29b-41d4-a716-446655440000",
        )

        assert mapping.salesforce_account_id == "001ABC123"
        assert mapping.posthog_org_id == "550e8400-e29b-41d4-a716-446655440000"


class TestSalesforceUsageUpdate(TestCase):
    def test_create_update(self):
        signals = UsageSignals(
            total_events_7d=10000,
            total_events_30d=50000,
            events_avg_daily_7d=1428.57,
        )
        update = SalesforceUsageUpdate(
            salesforce_account_id="001ABC123",
            signals=signals,
        )

        assert update.salesforce_account_id == "001ABC123"
        assert update.signals.total_events_7d == 10000


class TestUsageEnrichmentInputs(TestCase):
    def test_default_values(self):
        inputs = UsageEnrichmentInputs()

        assert inputs.batch_size == 100
        assert inputs.max_orgs is None
        assert inputs.specific_org_id is None

    def test_with_values(self):
        inputs = UsageEnrichmentInputs(
            batch_size=50,
            max_orgs=1000,
            specific_org_id="org-123",
        )

        assert inputs.batch_size == 50
        assert inputs.max_orgs == 1000
        assert inputs.specific_org_id == "org-123"


class TestPrepareSalesforceUpdateRecord(TestCase):
    def test_basic_signals(self):
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

        record = prepare_salesforce_update_record("001ABC123", signals)

        assert record["Id"] == "001ABC123"
        assert record["posthog_total_events_7d__c"] == 10000
        assert record["posthog_events_avg_daily_7d__c"] == 1428.57
        assert record["posthog_products_7d__c"] == "analytics,recordings"
        assert record["posthog_events_7d_momentum__c"] == 15.5
        assert record["posthog_total_events_30d__c"] == 50000
        assert record["posthog_events_avg_daily_30d__c"] == 1666.67
        assert record["posthog_products_30d__c"] == "analytics,feature_flags,recordings"
        assert record["posthog_events_30d_momentum__c"] == -5.0

    def test_none_values_excluded(self):
        signals = UsageSignals(
            total_events_7d=10000,
            events_avg_daily_7d=None,
            events_7d_momentum=None,
        )

        record = prepare_salesforce_update_record("001ABC123", signals)

        assert record["Id"] == "001ABC123"
        assert record["posthog_total_events_7d__c"] == 10000
        assert "posthog_events_avg_daily_7d__c" not in record
        assert "posthog_events_7d_momentum__c" not in record

    def test_empty_products_list(self):
        signals = UsageSignals(
            products_activated_7d=[],
            products_activated_30d=[],
        )

        record = prepare_salesforce_update_record("001ABC123", signals)

        assert record["posthog_products_7d__c"] == ""
        assert record["posthog_products_30d__c"] == ""

    def test_zero_events_included(self):
        signals = UsageSignals(
            total_events_7d=0,
            total_events_30d=0,
        )

        record = prepare_salesforce_update_record("001ABC123", signals)

        assert record["posthog_total_events_7d__c"] == 0
        assert record["posthog_total_events_30d__c"] == 0


class TestWorkflowParseInputs(TestCase):
    def test_parse_inputs_valid_json(self):
        inputs = SalesforceUsageEnrichmentWorkflow.parse_inputs(['{"batch_size": 50}'])

        assert inputs.batch_size == 50
        assert inputs.max_orgs is None
        assert inputs.specific_org_id is None

    def test_parse_inputs_all_fields(self):
        inputs = SalesforceUsageEnrichmentWorkflow.parse_inputs(
            ['{"batch_size": 25, "max_orgs": 100, "specific_org_id": "org-123"}']
        )

        assert inputs.batch_size == 25
        assert inputs.max_orgs == 100
        assert inputs.specific_org_id == "org-123"

    def test_parse_inputs_empty_json(self):
        inputs = SalesforceUsageEnrichmentWorkflow.parse_inputs(["{}"])

        assert inputs.batch_size == 100
        assert inputs.max_orgs is None
        assert inputs.specific_org_id is None

    def test_parse_inputs_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            SalesforceUsageEnrichmentWorkflow.parse_inputs(["invalid"])


WORKFLOW_MODULE = "posthog.temporal.salesforce_enrichment.usage_workflow"


class TestCacheOrgMappingsActivity(TestCase):
    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    @patch(f"{WORKFLOW_MODULE}.get_cached_org_mappings_count", new_callable=AsyncMock, return_value=100)
    async def test_cache_reused_when_exists(self, _mock_cache_count, _mock_close):
        result = await cache_org_mappings_activity()

        assert result["success"] is True
        assert result["total_mappings"] == 100
        assert result["cache_reused"] is True

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.store_org_mappings_in_redis", new_callable=AsyncMock)
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.get_cached_org_mappings_count", new_callable=AsyncMock, return_value=None)
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_queries_salesforce_on_cache_miss(self, _mock_close, _mock_cache_count, mock_sf_client, mock_store):
        mock_sf = MagicMock()
        mock_sf.query_all.return_value = {
            "records": [
                {"Id": "001ABC", "Posthog_Org_ID__c": "org-uuid-1"},
                {"Id": "001DEF", "Posthog_Org_ID__c": "org-uuid-2"},
                {"Id": "001GHI", "Posthog_Org_ID__c": None},  # Should be filtered out
            ]
        }
        mock_sf_client.return_value = mock_sf

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            result = await cache_org_mappings_activity()

        assert result["success"] is True
        assert result["total_mappings"] == 2
        assert "cache_reused" not in result

        mock_store.assert_called_once()
        stored_mappings = mock_store.call_args[0][0]
        assert len(stored_mappings) == 2
        assert stored_mappings[0]["posthog_org_id"] == "org-uuid-1"
        assert stored_mappings[1]["posthog_org_id"] == "org-uuid-2"


class TestUpdateSalesforceUsageActivity(TestCase):
    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_empty_updates_returns_zero(self, _mock_close, _mock_heartbeat):
        result = await update_salesforce_usage_activity([])
        assert result == 0

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_bulk_update_exception_returns_zero(self, _mock_close, mock_sf_client, _mock_heartbeat):
        signals = UsageSignals(total_events_7d=10000, events_avg_daily_7d=1428.57)
        updates = [
            SalesforceUsageUpdate(salesforce_account_id="001ABC", signals=signals),
            SalesforceUsageUpdate(salesforce_account_id="001DEF", signals=signals),
        ]

        mock_sf = MagicMock()
        mock_sf.bulk.Account.update.side_effect = Exception("Salesforce API error")
        mock_sf_client.return_value = mock_sf

        result = await update_salesforce_usage_activity(updates)
        assert result == 0

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_partial_success_counts_correctly(self, _mock_close, mock_sf_client, _mock_heartbeat):
        signals = UsageSignals(total_events_7d=10000)
        updates = [
            SalesforceUsageUpdate(salesforce_account_id="001ABC", signals=signals),
            SalesforceUsageUpdate(salesforce_account_id="001DEF", signals=signals),
            SalesforceUsageUpdate(salesforce_account_id="001GHI", signals=signals),
        ]

        mock_sf = MagicMock()
        mock_sf.bulk.Account.update.return_value = [
            {"id": "001ABC", "success": True},
            {"id": "001DEF", "success": False, "errors": ["Field not found"]},
            {"id": "001GHI", "success": True},
        ]
        mock_sf_client.return_value = mock_sf

        result = await update_salesforce_usage_activity(updates)
        assert result == 2

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_all_success(self, _mock_close, mock_sf_client, _mock_heartbeat):
        signals = UsageSignals(total_events_7d=10000)
        updates = [
            SalesforceUsageUpdate(salesforce_account_id="001ABC", signals=signals),
            SalesforceUsageUpdate(salesforce_account_id="001DEF", signals=signals),
        ]

        mock_sf = MagicMock()
        mock_sf.bulk.Account.update.return_value = [
            {"id": "001ABC", "success": True},
            {"id": "001DEF", "success": True},
        ]
        mock_sf_client.return_value = mock_sf

        result = await update_salesforce_usage_activity(updates)
        assert result == 2
