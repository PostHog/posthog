import json
import datetime as dt

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

from posthog.temporal.salesforce_enrichment.conversations_slack_workflow import (
    ConversationsSlackEnrichmentInputs,
    ConversationsSlackEnrichmentState,
    EnrichConversationsSlackPageResult,
    SalesforceConversationsSlackEnrichmentWorkflow,
    enrich_conversations_slack_page_activity,
    prepare_conversations_slack_update_record,
)

from ee.billing.salesforce_enrichment.conversations_signals import ConversationsSlackSignals

WORKFLOW_MODULE = "posthog.temporal.salesforce_enrichment.conversations_slack_workflow"


async def mock_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)


def _signals(
    org_id: str = "org-1",
    last_slack_activity: dt.datetime | None = None,
) -> ConversationsSlackSignals:
    return ConversationsSlackSignals(
        posthog_organization_id=org_id,
        slack_channel_url="https://app.slack.com/client/T123/C123",
        slack_issue_count=3,
        slack_user_count=12,
        last_slack_activity=last_slack_activity or dt.datetime(2026, 6, 29, 15, 30, tzinfo=dt.UTC),
        most_recent_support_ticket_url=f"https://us.posthog.com/project/2/support/tickets/{1000 if org_id == 'org-1' else 1001}",
    )


class TestPrepareConversationsSlackUpdateRecord(SimpleTestCase):
    def test_formats_last_slack_activity_as_salesforce_date(self):
        record = prepare_conversations_slack_update_record("001ABC", _signals())

        assert record == {
            "Id": "001ABC",
            "Slack_Channel__c": "https://app.slack.com/client/T123/C123",
            "slack_issue_count__c": 3,
            "slack_user_count__c": 12,
            "last_slack_activity__c": "2026-06-29",
            "Most_Recent_Support_Ticket__c": "https://us.posthog.com/project/2/support/tickets/1000",
        }

    def test_omits_none_fields(self):
        signals = ConversationsSlackSignals(
            posthog_organization_id="org-1",
            slack_channel_url=None,
            slack_issue_count=0,
            slack_user_count=None,
            last_slack_activity=None,
            most_recent_support_ticket_url=None,
        )

        record = prepare_conversations_slack_update_record("001ABC", signals)

        assert record == {"Id": "001ABC", "slack_issue_count__c": 0}


class TestWorkflowParseInputs(SimpleTestCase):
    def test_defaults(self):
        inputs = SalesforceConversationsSlackEnrichmentWorkflow.parse_inputs(["{}"])

        assert inputs.batch_size == 100
        assert inputs.max_orgs is None
        assert inputs.specific_org_id is None
        assert inputs.state is None

    def test_state_roundtrip(self):
        payload = json.dumps(
            {
                "max_orgs": 500,
                "state": {
                    "page_offset": 100,
                    "total_processed": 100,
                    "total_updated": 90,
                    "error_count": 1,
                    "errors": ["one failed"],
                },
            }
        )

        inputs = SalesforceConversationsSlackEnrichmentWorkflow.parse_inputs([payload])

        assert inputs.max_orgs == 500
        assert inputs.state is not None
        assert inputs.state.page_offset == 100
        assert inputs.state.total_updated == 90

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            SalesforceConversationsSlackEnrichmentWorkflow.parse_inputs(["invalid"])


class TestEnrichConversationsSlackPageActivity(SimpleTestCase):
    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.bulk_update_salesforce_accounts", return_value=(2, 0))
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.aggregate_conversations_slack_signals_for_orgs")
    @patch(f"{WORKFLOW_MODULE}.get_org_mappings_page_from_redis", new_callable=AsyncMock)
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_enriches_page_successfully(
        self,
        _mock_close,
        mock_get_page,
        mock_aggregate,
        mock_sf_client,
        mock_bulk,
        _mock_heartbeat,
    ):
        mock_get_page.return_value = [
            {"salesforce_account_id": "001ABC", "posthog_org_id": "org-1"},
            {"salesforce_account_id": "001DEF", "posthog_org_id": "org-2"},
        ]
        mock_aggregate.return_value = {
            "org-1": _signals("org-1"),
            "org-2": _signals("org-2", dt.datetime(2026, 6, 28, 10, 0, tzinfo=dt.UTC)),
        }
        mock_sf = MagicMock()
        mock_sf_client.return_value = mock_sf

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            result = await enrich_conversations_slack_page_activity(0, 10000, 100)

        assert result.page_size == 2
        assert result.processed == 2
        assert result.updated == 2
        assert result.errors == []
        mock_get_page.assert_called_once_with(0, 10000)
        mock_bulk.assert_called_once()

        sent_records = mock_bulk.call_args[0][1]
        assert sent_records[0]["Id"] == "001ABC"
        assert sent_records[0]["last_slack_activity__c"] == "2026-06-29"
        assert sent_records[1]["Id"] == "001DEF"
        assert sent_records[1]["last_slack_activity__c"] == "2026-06-28"

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.bulk_update_salesforce_accounts", side_effect=Exception("sfdc down"))
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.aggregate_conversations_slack_signals_for_orgs")
    @patch(f"{WORKFLOW_MODULE}.get_org_mappings_page_from_redis", new_callable=AsyncMock)
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_sfdc_transport_exception_propagates_for_retry(
        self,
        _mock_close,
        mock_get_page,
        mock_aggregate,
        mock_sf_client,
        mock_bulk,
        _mock_heartbeat,
    ):
        mock_get_page.return_value = [{"salesforce_account_id": "001ABC", "posthog_org_id": "org-1"}]
        mock_aggregate.return_value = {"org-1": _signals("org-1")}
        mock_sf_client.return_value = MagicMock()

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            with pytest.raises(Exception, match="sfdc down"):
                await enrich_conversations_slack_page_activity(0, 10000, 100)

        _, kwargs = mock_bulk.call_args
        assert kwargs.get("raise_on_batch_error") is True

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.bulk_update_salesforce_accounts", return_value=(1, 1))
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.aggregate_conversations_slack_signals_for_orgs")
    @patch(f"{WORKFLOW_MODULE}.get_org_mappings_page_from_redis", new_callable=AsyncMock)
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_partial_bulk_update_failure_records_error(
        self,
        _mock_close,
        mock_get_page,
        mock_aggregate,
        mock_sf_client,
        mock_bulk,
        _mock_heartbeat,
    ):
        mock_get_page.return_value = [
            {"salesforce_account_id": "001ABC", "posthog_org_id": "org-1"},
            {"salesforce_account_id": "001DEF", "posthog_org_id": "org-2"},
        ]
        mock_aggregate.return_value = {
            "org-1": _signals("org-1"),
            "org-2": _signals("org-2"),
        }
        mock_sf_client.return_value = MagicMock()

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            result = await enrich_conversations_slack_page_activity(0, 10000, 100)

        assert result.updated == 1
        assert result.errors == ["sfdc_bulk_update_failed_count=1"]
        _, kwargs = mock_bulk.call_args
        assert kwargs.get("raise_on_batch_error") is True

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.get_org_mappings_page_from_redis", new_callable=AsyncMock)
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_returns_empty_on_cache_miss(self, _mock_close, mock_get_page, _mock_heartbeat):
        mock_get_page.return_value = None

        result = await enrich_conversations_slack_page_activity(0, 10000, 100)

        assert result == EnrichConversationsSlackPageResult(page_size=0, processed=0, updated=0, errors=[])


class TestProductionModeContinueAsNew(SimpleTestCase):
    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_continues_as_new_when_page_is_full(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                None,
                EnrichConversationsSlackPageResult(page_size=10000, processed=10000, updated=500, errors=[]),
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        workflow = SalesforceConversationsSlackEnrichmentWorkflow()
        await workflow._run_production_mode(ConversationsSlackEnrichmentInputs(batch_size=100))

        mock_workflow.continue_as_new.assert_called_once()
        next_inputs = mock_workflow.continue_as_new.call_args[0][0]
        assert next_inputs.state.page_offset == 10000
        assert next_inputs.state.total_processed == 10000
        assert next_inputs.state.total_updated == 500

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_returns_result_on_last_page(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            return_value=EnrichConversationsSlackPageResult(page_size=5000, processed=5000, updated=250, errors=[]),
        )
        mock_workflow.continue_as_new = MagicMock()

        workflow = SalesforceConversationsSlackEnrichmentWorkflow()
        state = ConversationsSlackEnrichmentState(page_offset=10000, total_processed=10000, total_updated=500)
        result = await workflow._run_production_mode(ConversationsSlackEnrichmentInputs(batch_size=100, state=state))

        mock_workflow.continue_as_new.assert_not_called()
        assert result["total_orgs_processed"] == 15000
        assert result["total_orgs_updated"] == 750
