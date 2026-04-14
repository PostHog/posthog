import json
import datetime as dt

from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.salesforce_enrichment.stripe_workflow import (
    EnrichStripePageResult,
    SalesforceStripeEnrichmentWorkflow,
    StripeEnrichmentInputs,
    StripeEnrichmentState,
    _compose_billing_street,
    _soql_quote,
    enrich_stripe_page_activity,
    prepare_stripe_update_record,
)

from ee.billing.salesforce_enrichment.stripe_signals import StripeSignals

WORKFLOW_MODULE = "posthog.temporal.salesforce_enrichment.stripe_workflow"


def _signals(
    org_id: str = "org-1",
    stripe_id: str | None = "cus_1",
    line1: str | None = "1 Main St",
    line2: str | None = None,
    last_changed_at: dt.datetime | None = None,
) -> StripeSignals:
    return StripeSignals(
        posthog_organization_id=org_id,
        billing_customer_id="bc-1",
        billing_customer_name="Acme Inc",
        stripe_customer_id=stripe_id,
        address_line_1=line1,
        address_line_2=line2,
        address_city="SF",
        address_state="CA",
        address_postal_code="94107",
        address_country="US",
        last_changed_at=last_changed_at or dt.datetime(2026, 4, 10, 12, 0, tzinfo=dt.UTC),
    )


async def mock_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)


class TestSoqlQuote(TestCase):
    def test_basic(self):
        assert _soql_quote("abc") == "'abc'"

    def test_escapes_single_quote(self):
        assert _soql_quote("ab'c") == "'ab\\'c'"

    def test_escapes_backslash(self):
        assert _soql_quote("a\\b") == "'a\\\\b'"


class TestComposeBillingStreet(TestCase):
    def test_both_lines(self):
        s = _signals(line1="1 Main St", line2="Suite 200")
        assert _compose_billing_street(s) == "1 Main St\nSuite 200"

    def test_line_1_only(self):
        s = _signals(line1="1 Main St", line2=None)
        assert _compose_billing_street(s) == "1 Main St"

    def test_line_2_only(self):
        s = _signals(line1=None, line2="Suite 200")
        assert _compose_billing_street(s) == "Suite 200"

    def test_neither(self):
        s = _signals(line1=None, line2=None)
        assert _compose_billing_street(s) is None


class TestPrepareStripeUpdateRecord(TestCase):
    def test_full_record(self):
        record = prepare_stripe_update_record("001ABC", _signals(line2="Suite 200"))

        assert record["Id"] == "001ABC"
        assert record["Name"] == "Acme Inc"
        assert record["Stripe_id__c"] == "cus_1"
        assert record["BillingStreet"] == "1 Main St\nSuite 200"
        assert record["BillingCity"] == "SF"
        assert record["BillingState"] == "CA"
        assert record["BillingPostalCode"] == "94107"
        assert record["BillingCountry"] == "US"

    def test_none_values_omitted(self):
        signals = StripeSignals(
            posthog_organization_id="org-1",
            billing_customer_id="bc-1",
            billing_customer_name=None,
            stripe_customer_id=None,
            address_line_1=None,
            address_line_2=None,
            address_city=None,
            address_state=None,
            address_postal_code=None,
            address_country=None,
            last_changed_at=dt.datetime(2026, 4, 10, tzinfo=dt.UTC),
        )
        record = prepare_stripe_update_record("001ABC", signals)

        assert record == {"Id": "001ABC"}


class TestWorkflowParseInputs(TestCase):
    def test_defaults(self):
        inputs = SalesforceStripeEnrichmentWorkflow.parse_inputs(["{}"])

        assert inputs.force_full_refresh is False
        assert inputs.max_rows is None
        assert inputs.state is None

    def test_full_refresh(self):
        inputs = SalesforceStripeEnrichmentWorkflow.parse_inputs(['{"force_full_refresh": true}'])

        assert inputs.force_full_refresh is True

    def test_state_roundtrip(self):
        payload = json.dumps(
            {
                "max_rows": 500,
                "state": {
                    "page_offset": 100,
                    "total_rows_fetched": 100,
                    "total_updated": 90,
                    "total_skipped_no_account": 10,
                    "error_count": 0,
                    "errors": [],
                    "resolved_since": "2026-04-10T12:00:00+00:00",
                    "pending_watermark": "2026-04-11T12:00:00+00:00",
                },
            }
        )
        inputs = SalesforceStripeEnrichmentWorkflow.parse_inputs([payload])

        assert inputs.max_rows == 500
        assert inputs.state is not None
        assert inputs.state.page_offset == 100
        assert inputs.state.resolved_since == "2026-04-10T12:00:00+00:00"


class TestEnrichStripePageActivity(IsolatedAsyncioTestCase):
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.bulk_update_salesforce_accounts", return_value=(2, 0))
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.fetch_stripe_signals")
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_happy_path(
        self,
        _mock_close,
        mock_fetch,
        mock_sf_client,
        mock_bulk,
        _mock_heartbeat,
    ):
        mock_fetch.return_value = [
            _signals(org_id="org-1", last_changed_at=dt.datetime(2026, 4, 10, tzinfo=dt.UTC)),
            _signals(org_id="org-2", last_changed_at=dt.datetime(2026, 4, 11, tzinfo=dt.UTC)),
        ]

        mock_sf = MagicMock()
        mock_sf.query_all.return_value = {
            "records": [
                {"Id": "001ABC", "Posthog_Org_ID__c": "org-1"},
                {"Id": "001DEF", "Posthog_Org_ID__c": "org-2"},
            ]
        }
        mock_sf_client.return_value = mock_sf

        from posthog.temporal.salesforce_enrichment.stripe_workflow import EnrichStripePageInputs

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            result = await enrich_stripe_page_activity(
                EnrichStripePageInputs(since=None, offset=0, page_size=5000, sfdc_batch_size=200)
            )

        assert result.rows_fetched == 2
        assert result.updated == 2
        assert result.skipped_no_account == 0
        assert result.errors == []
        assert result.max_last_changed_at == "2026-04-11T00:00:00+00:00"
        mock_bulk.assert_called_once()
        sent_records = mock_bulk.call_args[0][1]
        assert len(sent_records) == 2
        assert sent_records[0]["Name"] == "Acme Inc"

    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.bulk_update_salesforce_accounts", return_value=(1, 0))
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.fetch_stripe_signals")
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_skips_rows_with_no_matching_sfdc_account(
        self,
        _mock_close,
        mock_fetch,
        mock_sf_client,
        mock_bulk,
        _mock_heartbeat,
    ):
        mock_fetch.return_value = [
            _signals(org_id="org-1"),
            _signals(org_id="org-missing"),
        ]

        mock_sf = MagicMock()
        mock_sf.query_all.return_value = {"records": [{"Id": "001ABC", "Posthog_Org_ID__c": "org-1"}]}
        mock_sf_client.return_value = mock_sf

        from posthog.temporal.salesforce_enrichment.stripe_workflow import EnrichStripePageInputs

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            result = await enrich_stripe_page_activity(
                EnrichStripePageInputs(since=None, offset=0, page_size=5000, sfdc_batch_size=200)
            )

        assert result.rows_fetched == 2
        assert result.updated == 1
        assert result.skipped_no_account == 1
        sent_records = mock_bulk.call_args[0][1]
        assert len(sent_records) == 1
        assert sent_records[0]["Id"] == "001ABC"

    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.fetch_stripe_signals", return_value=[])
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_empty_page_returns_zero(self, _mock_close, _mock_fetch, _mock_heartbeat):
        from posthog.temporal.salesforce_enrichment.stripe_workflow import EnrichStripePageInputs

        result = await enrich_stripe_page_activity(
            EnrichStripePageInputs(since=None, offset=0, page_size=5000, sfdc_batch_size=200)
        )

        assert result.rows_fetched == 0
        assert result.updated == 0
        assert result.max_last_changed_at is None

    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.bulk_update_salesforce_accounts", side_effect=Exception("sfdc down"))
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.fetch_stripe_signals")
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_sfdc_exception_captured_as_error(
        self, _mock_close, mock_fetch, mock_sf_client, _mock_bulk, _mock_heartbeat
    ):
        mock_fetch.return_value = [_signals(org_id="org-1")]
        mock_sf = MagicMock()
        mock_sf.query_all.return_value = {"records": [{"Id": "001ABC", "Posthog_Org_ID__c": "org-1"}]}
        mock_sf_client.return_value = mock_sf

        from posthog.temporal.salesforce_enrichment.stripe_workflow import EnrichStripePageInputs

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            result = await enrich_stripe_page_activity(
                EnrichStripePageInputs(since=None, offset=0, page_size=5000, sfdc_batch_size=200)
            )

        assert result.rows_fetched == 1
        assert result.updated == 0
        assert len(result.errors) == 1
        assert "sfdc down" in result.errors[0]


class TestWorkflowRun(IsolatedAsyncioTestCase):
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_resolves_watermark_on_first_iteration(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                "2026-04-10T00:00:00+00:00",  # get_stripe_watermark_activity
                EnrichStripePageResult(
                    rows_fetched=100,
                    updated=90,
                    skipped_no_account=10,
                    errors=[],
                    max_last_changed_at="2026-04-12T00:00:00+00:00",
                ),
                None,  # commit_stripe_watermark_activity
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500)
        result = await wf.run(inputs)

        assert mock_workflow.execute_activity.await_count == 3
        assert result["total_rows_fetched"] == 100
        assert result["total_updated"] == 90
        assert result["committed_watermark"] == "2026-04-12T00:00:00+00:00"
        mock_workflow.continue_as_new.assert_not_called()

    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_continues_as_new_when_page_full(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                None,  # watermark fetch returns None (first run, full backfill)
                EnrichStripePageResult(
                    rows_fetched=500,
                    updated=500,
                    skipped_no_account=0,
                    errors=[],
                    max_last_changed_at="2026-04-12T00:00:00+00:00",
                ),
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500)
        await wf.run(inputs)

        mock_workflow.continue_as_new.assert_called_once()
        call_args = mock_workflow.continue_as_new.call_args[0][0]
        assert call_args.state.page_offset == 500
        assert call_args.state.pending_watermark == "2026-04-12T00:00:00+00:00"
        assert call_args.state.resolved_since is None

    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_force_full_refresh_skips_watermark_read(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                EnrichStripePageResult(
                    rows_fetched=10,
                    updated=10,
                    skipped_no_account=0,
                    errors=[],
                    max_last_changed_at="2026-04-12T00:00:00+00:00",
                ),
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500, force_full_refresh=True)
        result = await wf.run(inputs)

        # Exactly one activity call — the page enrichment. Neither get_watermark
        # nor commit_watermark should run.
        assert mock_workflow.execute_activity.await_count == 1
        assert result["committed_watermark"] == "2026-04-12T00:00:00+00:00"

    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_continuation_does_not_refetch_since(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                EnrichStripePageResult(
                    rows_fetched=10,
                    updated=10,
                    skipped_no_account=0,
                    errors=[],
                    max_last_changed_at="2026-04-13T00:00:00+00:00",
                ),
                None,  # commit_watermark
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        state = StripeEnrichmentState(
            page_offset=500,
            total_rows_fetched=500,
            total_updated=500,
            resolved_since="2026-04-10T00:00:00+00:00",
            pending_watermark="2026-04-12T00:00:00+00:00",
        )
        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500, state=state)
        result = await wf.run(inputs)

        # Page size 10 < inputs.page_size 500 — this is the final iteration.
        assert result["total_rows_fetched"] == 510
        assert result["committed_watermark"] == "2026-04-13T00:00:00+00:00"
        mock_workflow.continue_as_new.assert_not_called()

    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_errors_from_page_accumulate_and_cap(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                None,  # watermark
                EnrichStripePageResult(
                    rows_fetched=10,
                    updated=5,
                    skipped_no_account=0,
                    errors=[f"err-{i}" for i in range(15)],
                    max_last_changed_at="2026-04-12T00:00:00+00:00",
                ),
                None,  # commit watermark
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500)
        result = await wf.run(inputs)

        assert result["error_count"] == 15
        assert len(result["errors"]) == 10
