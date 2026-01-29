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
            active_users_7d=100,
            active_users_30d=500,
            sessions_7d=200,
        )
        update = SalesforceUsageUpdate(
            salesforce_account_id="001ABC123",
            signals=signals,
        )

        assert update.salesforce_account_id == "001ABC123"
        assert update.signals.active_users_7d == 100


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
            active_users_7d=100,
            active_users_30d=500,
            sessions_7d=200,
            sessions_30d=800,
            events_per_session_7d=10.5,
            events_per_session_30d=9.8,
            products_activated_7d=["analytics", "recordings"],
            products_activated_30d=["analytics", "recordings", "feature_flags"],
            days_since_last_login=3,
        )

        record = prepare_salesforce_update_record("001ABC123", signals)

        assert record["Id"] == "001ABC123"
        assert record["posthog_active_users_7d__c"] == 100
        assert record["posthog_active_users_30d__c"] == 500
        assert record["posthog_sessions_7d__c"] == 200
        assert record["posthog_sessions_30d__c"] == 800
        assert record["posthog_events_per_session_7d__c"] == 10.5
        assert record["posthog_events_per_session_30d__c"] == 9.8
        assert record["posthog_products_7d__c"] == "analytics,recordings"
        assert record["posthog_products_30d__c"] == "analytics,feature_flags,recordings"
        assert record["posthog_last_login_days__c"] == 3

    def test_with_momentum(self):
        signals = UsageSignals(
            active_users_7d=100,
            active_users_30d=500,
            active_users_7d_momentum=25.5,
            active_users_30d_momentum=-10.2,
            sessions_7d_momentum=15.0,
            sessions_30d_momentum=5.0,
            events_per_session_7d_momentum=2.5,
            events_per_session_30d_momentum=-1.5,
        )

        record = prepare_salesforce_update_record("001ABC123", signals)

        assert record["posthog_active_users_7d_momentum__c"] == 25.5
        assert record["posthog_active_users_30d_momentum__c"] == -10.2
        assert record["posthog_sessions_7d_momentum__c"] == 15.0
        assert record["posthog_sessions_30d_momentum__c"] == 5.0
        assert record["posthog_eps_7d_momentum__c"] == 2.5
        assert record["posthog_eps_30d_momentum__c"] == -1.5

    def test_none_values_excluded(self):
        signals = UsageSignals(
            active_users_7d=100,
            events_per_session_7d=None,
            days_since_last_login=None,
            active_users_7d_momentum=None,
        )

        record = prepare_salesforce_update_record("001ABC123", signals)

        assert record["Id"] == "001ABC123"
        assert record["posthog_active_users_7d__c"] == 100
        assert "posthog_events_per_session_7d__c" not in record
        assert "posthog_last_login_days__c" not in record
        assert "posthog_active_users_7d_momentum__c" not in record

    def test_per_user_metrics(self):
        signals = UsageSignals(
            insights_per_user_7d=2.5,
            insights_per_user_30d=3.2,
            dashboards_per_user_7d=1.0,
            dashboards_per_user_30d=1.5,
        )

        record = prepare_salesforce_update_record("001ABC123", signals)

        assert record["posthog_insights_per_user_7d__c"] == 2.5
        assert record["posthog_insights_per_user_30d__c"] == 3.2
        assert record["posthog_dashboards_per_user_7d__c"] == 1.0
        assert record["posthog_dashboards_per_user_30d__c"] == 1.5

    def test_empty_products_list(self):
        signals = UsageSignals(
            products_activated_7d=[],
            products_activated_30d=[],
        )

        record = prepare_salesforce_update_record("001ABC123", signals)

        assert record["posthog_products_7d__c"] == ""
        assert record["posthog_products_30d__c"] == ""


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

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
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
        signals = UsageSignals(active_users_7d=100, sessions_7d=50)
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
        signals = UsageSignals(active_users_7d=100)
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
        signals = UsageSignals(active_users_7d=100)
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
