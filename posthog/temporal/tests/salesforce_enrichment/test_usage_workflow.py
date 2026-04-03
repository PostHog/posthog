import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase

from posthog.temporal.salesforce_enrichment.usage_workflow import (
    EnrichPageResult,
    SalesforceUsageEnrichmentWorkflow,
    UsageEnrichmentInputs,
    UsageEnrichmentState,
    cache_org_mappings_activity,
    enrich_org_page_activity,
    prepare_salesforce_update_record,
)

from ee.billing.salesforce_enrichment.usage_signals import UsageSignals


async def mock_to_thread(fn, *args, **kwargs):
    """Mock asyncio.to_thread that returns an awaitable."""
    return fn(*args, **kwargs)


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


class TestEnrichOrgPageActivity(TestCase):
    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.get_org_mappings_page_from_redis", new_callable=AsyncMock)
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_enriches_page_successfully(self, _mock_close, mock_get_page, mock_sf_client, _mock_heartbeat):
        mock_get_page.return_value = [
            {"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"},
            {"salesforce_account_id": "001DEF", "posthog_org_id": "uuid-2"},
        ]

        mock_sf = MagicMock()
        mock_sf.bulk.Account.update.return_value = [
            {"id": "001ABC", "success": True},
            {"id": "001DEF", "success": True},
        ]
        mock_sf_client.return_value = mock_sf

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            result = await enrich_org_page_activity(0, 10000, 100)

        assert result.page_size == 2
        assert result.processed == 2
        assert result.updated == 2
        assert result.errors == []
        mock_get_page.assert_called_once_with(0, 10000)

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.get_org_mappings_page_from_redis", new_callable=AsyncMock)
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_returns_empty_on_cache_miss(self, _mock_close, mock_get_page, _mock_heartbeat):
        mock_get_page.return_value = None

        result = await enrich_org_page_activity(0, 10000, 100)

        assert result.page_size == 0
        assert result.processed == 0
        assert result.updated == 0

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.get_org_mappings_page_from_redis", new_callable=AsyncMock)
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_returns_empty_on_empty_page(self, _mock_close, mock_get_page, _mock_heartbeat):
        mock_get_page.return_value = []

        result = await enrich_org_page_activity(5000, 10000, 100)

        assert result.page_size == 0
        assert result.processed == 0

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.get_org_mappings_page_from_redis", new_callable=AsyncMock)
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_handles_salesforce_partial_failure(
        self, _mock_close, mock_get_page, mock_sf_client, _mock_heartbeat
    ):
        mock_get_page.return_value = [
            {"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"},
            {"salesforce_account_id": "001DEF", "posthog_org_id": "uuid-2"},
            {"salesforce_account_id": "001GHI", "posthog_org_id": "uuid-3"},
        ]

        mock_sf = MagicMock()
        mock_sf.bulk.Account.update.return_value = [
            {"id": "001ABC", "success": True},
            {"id": "001DEF", "success": False, "errors": ["Field not found"]},
            {"id": "001GHI", "success": True},
        ]
        mock_sf_client.return_value = mock_sf

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            result = await enrich_org_page_activity(0, 10000, 100)

        assert result.page_size == 3
        assert result.processed == 3
        assert result.updated == 2

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.get_org_mappings_page_from_redis", new_callable=AsyncMock)
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_handles_batch_exception(self, _mock_close, mock_get_page, mock_sf_client, _mock_heartbeat):
        mock_get_page.return_value = [
            {"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"},
        ]

        mock_sf = MagicMock()
        mock_sf_client.return_value = mock_sf

        with patch(
            f"{WORKFLOW_MODULE}.aggregate_usage_signals_for_orgs",
            side_effect=Exception("DB connection failed"),
        ):
            with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
                result = await enrich_org_page_activity(0, 10000, 100)

        assert result.page_size == 1
        assert result.processed == 0
        assert len(result.errors) == 1
        assert "DB connection failed" in result.errors[0]

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.get_org_mappings_page_from_redis", new_callable=AsyncMock)
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_passes_offset_to_redis(self, _mock_close, mock_get_page, _mock_heartbeat):
        mock_get_page.return_value = []

        await enrich_org_page_activity(5000, 2500, 50)

        mock_get_page.assert_called_once_with(5000, 2500)


WORKFLOW_CLASS = f"{WORKFLOW_MODULE}.SalesforceUsageEnrichmentWorkflow"


class TestProductionModeContinueAsNew(TestCase):
    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_continues_as_new_when_page_is_full(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                None,  # cache_org_mappings_activity
                EnrichPageResult(page_size=10000, processed=10000, updated=9500, errors=[]),
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceUsageEnrichmentWorkflow()
        inputs = UsageEnrichmentInputs(batch_size=100)
        await wf._run_production_mode(inputs)

        mock_workflow.continue_as_new.assert_called_once()
        call_args = mock_workflow.continue_as_new.call_args[0][0]
        assert call_args.state.page_offset == 10000
        assert call_args.state.total_processed == 10000
        assert call_args.state.total_updated == 9500

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_returns_result_on_last_page(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            return_value=EnrichPageResult(page_size=5000, processed=5000, updated=4800, errors=[]),
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceUsageEnrichmentWorkflow()
        state = UsageEnrichmentState(page_offset=10000, total_processed=10000, total_updated=9500)
        inputs = UsageEnrichmentInputs(batch_size=100, state=state)
        result = await wf._run_production_mode(inputs)

        mock_workflow.continue_as_new.assert_not_called()
        assert result["total_orgs_processed"] == 15000
        assert result["total_orgs_updated"] == 14300

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_max_orgs_stops_before_limit(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            return_value=EnrichPageResult(page_size=500, processed=500, updated=480, errors=[]),
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceUsageEnrichmentWorkflow()
        state = UsageEnrichmentState(page_offset=0, total_processed=500, total_updated=480)
        inputs = UsageEnrichmentInputs(batch_size=100, max_orgs=500, state=state)
        result = await wf._run_production_mode(inputs)

        # Should return immediately since total_processed == max_orgs
        mock_workflow.execute_activity.assert_not_called()
        assert result["total_orgs_processed"] == 500

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_empty_page_returns_result(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                None,  # cache_org_mappings_activity
                EnrichPageResult(page_size=0, processed=0, updated=0, errors=[]),
            ]
        )

        wf = SalesforceUsageEnrichmentWorkflow()
        inputs = UsageEnrichmentInputs(batch_size=100)
        result = await wf._run_production_mode(inputs)

        assert result["total_orgs_processed"] == 0
        assert result["total_orgs_updated"] == 0

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_errors_capped_at_10_across_continuations(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            return_value=EnrichPageResult(
                page_size=5000, processed=5000, updated=0, errors=[f"error-{i}" for i in range(8)]
            ),
        )

        wf = SalesforceUsageEnrichmentWorkflow()
        state = UsageEnrichmentState(
            page_offset=10000,
            total_processed=10000,
            error_count=5,
            errors=[f"prev-error-{i}" for i in range(5)],
        )
        inputs = UsageEnrichmentInputs(batch_size=100, state=state)
        result = await wf._run_production_mode(inputs)

        # error_count reflects all errors, but errors list is capped at 10
        assert result["error_count"] == 13
        assert len(result["errors"]) == 10
