import json
import datetime as dt

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.temporal.salesforce_enrichment.stripe_workflow import (
    EnrichStripePageInputs,
    EnrichStripePageResult,
    SalesforceStripeEnrichmentWorkflow,
    StripeEnrichmentInputs,
    StripeEnrichmentState,
    _compose_billing_street,
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


class TestComposeBillingStreet(SimpleTestCase):
    @parameterized.expand(
        [
            ("both_lines", "1 Main St", "Suite 200", "1 Main St\nSuite 200"),
            ("line_1_only", "1 Main St", None, "1 Main St"),
            ("line_2_only", None, "Suite 200", "Suite 200"),
            ("neither", None, None, None),
        ]
    )
    def test_compose(self, _name, line1, line2, expected):
        assert _compose_billing_street(_signals(line1=line1, line2=line2)) == expected


class TestPrepareStripeUpdateRecord(SimpleTestCase):
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


class TestWorkflowParseInputs(SimpleTestCase):
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
                    "total_rows_fetched": 100,
                    "total_updated": 90,
                    "total_skipped_no_account": 10,
                    "error_count": 0,
                    "errors": [],
                    "pending_watermark_ts": "2026-04-11T12:00:00+00:00",
                    "pending_watermark_org_id": "org-99",
                    "cursor_last_changed_at": "2026-04-11T00:00:00+00:00",
                    "cursor_org_id": "org-99",
                },
            }
        )
        inputs = SalesforceStripeEnrichmentWorkflow.parse_inputs([payload])

        assert inputs.max_rows == 500
        assert inputs.state is not None
        assert inputs.state.total_rows_fetched == 100
        assert inputs.state.pending_watermark_ts == "2026-04-11T12:00:00+00:00"
        assert inputs.state.pending_watermark_org_id == "org-99"
        assert inputs.state.cursor_last_changed_at == "2026-04-11T00:00:00+00:00"
        assert inputs.state.cursor_org_id == "org-99"


class TestEnrichStripePageActivity(SimpleTestCase):
    @pytest.mark.asyncio
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

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            result = await enrich_stripe_page_activity(EnrichStripePageInputs(page_size=5000))

        assert result.rows_fetched == 2
        assert result.updated == 2
        assert result.skipped_no_account == 0
        assert result.errors == []
        assert result.next_cursor_last_changed_at == "2026-04-11T00:00:00+00:00"
        assert result.next_cursor_org_id == "org-2"
        mock_bulk.assert_called_once()
        sent_records = mock_bulk.call_args[0][1]
        assert len(sent_records) == 2
        assert sent_records[0]["Name"] == "Acme Inc"

    @pytest.mark.asyncio
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

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            result = await enrich_stripe_page_activity(EnrichStripePageInputs(page_size=5000))

        assert result.rows_fetched == 2
        assert result.updated == 1
        assert result.skipped_no_account == 1
        sent_records = mock_bulk.call_args[0][1]
        assert len(sent_records) == 1
        assert sent_records[0]["Id"] == "001ABC"

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.fetch_stripe_signals", return_value=[])
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_empty_page_returns_zero(self, _mock_close, _mock_fetch, _mock_heartbeat):
        result = await enrich_stripe_page_activity(EnrichStripePageInputs(page_size=5000))

        assert result.rows_fetched == 0
        assert result.updated == 0
        assert result.next_cursor_last_changed_at is None
        assert result.next_cursor_org_id is None

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.bulk_update_salesforce_accounts", side_effect=Exception("sfdc down"))
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.fetch_stripe_signals")
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_sfdc_transport_exception_propagates_for_retry(
        self, _mock_close, mock_fetch, mock_sf_client, mock_bulk, _mock_heartbeat
    ):
        """Transport failures must bubble up so Temporal retries the whole page.

        Previously the activity caught the exception and returned a soft error,
        which meant the activity's retry policy was never exercised and transient
        429/5xx/network failures left rows stale until the next daily run.
        """
        mock_fetch.return_value = [_signals(org_id="org-1")]
        mock_sf = MagicMock()
        mock_sf.query_all.return_value = {"records": [{"Id": "001ABC", "Posthog_Org_ID__c": "org-1"}]}
        mock_sf_client.return_value = mock_sf

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            with pytest.raises(Exception, match="sfdc down"):
                await enrich_stripe_page_activity(EnrichStripePageInputs(page_size=5000))

        _, kwargs = mock_bulk.call_args
        assert kwargs.get("raise_on_batch_error") is True

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.bulk_update_salesforce_accounts", return_value=(1, 1))
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.fetch_stripe_signals")
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_partial_bulk_update_failure_records_error(
        self,
        _mock_close,
        mock_fetch,
        mock_sf_client,
        _mock_bulk,
        _mock_heartbeat,
    ):
        mock_fetch.return_value = [
            _signals(org_id="org-1"),
            _signals(org_id="org-2"),
        ]
        mock_sf = MagicMock()
        mock_sf.query_all.return_value = {
            "records": [
                {"Id": "001ABC", "Posthog_Org_ID__c": "org-1"},
                {"Id": "001DEF", "Posthog_Org_ID__c": "org-2"},
            ]
        }
        mock_sf_client.return_value = mock_sf

        with patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread):
            result = await enrich_stripe_page_activity(EnrichStripePageInputs(page_size=5000))

        # Partial failure: 1 row succeeded, 1 row was rejected by Salesforce.
        # We still count the success in ``updated`` but surface the failure via errors
        # so the workflow-level ``error_count`` reflects it.
        assert result.updated == 1
        assert result.errors == ["sfdc_bulk_update_failed_count=1"]

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.Heartbeater")
    @patch(f"{WORKFLOW_MODULE}.bulk_update_salesforce_accounts", return_value=(250, 0))
    @patch(f"{WORKFLOW_MODULE}.get_salesforce_client")
    @patch(f"{WORKFLOW_MODULE}.fetch_stripe_signals")
    @patch(f"{WORKFLOW_MODULE}.close_old_connections")
    async def test_soql_lookup_chunks_large_pages(
        self,
        _mock_close,
        mock_fetch,
        mock_sf_client,
        _mock_bulk,
        _mock_heartbeat,
    ):
        # Force two SOQL lookup round trips by dropping the chunk size for this
        # test so we don't need 500+ fixtures to cross the boundary.
        mock_fetch.return_value = [_signals(org_id=f"org-{i}") for i in range(250)]
        mock_sf = MagicMock()
        mock_sf.query_all.return_value = {
            "records": [{"Id": f"001{i:04d}", "Posthog_Org_ID__c": f"org-{i}"} for i in range(250)]
        }
        mock_sf_client.return_value = mock_sf

        with (
            patch(f"{WORKFLOW_MODULE}._SFDC_LOOKUP_CHUNK_SIZE", 100),
            patch(f"{WORKFLOW_MODULE}.asyncio.to_thread", side_effect=mock_to_thread),
        ):
            result = await enrich_stripe_page_activity(EnrichStripePageInputs(page_size=5000))

        # 250 org ids at chunk size 100 → 3 lookup calls (100 + 100 + 50).
        assert mock_sf.query_all.call_count == 3
        assert result.rows_fetched == 250
        assert result.skipped_no_account == 0


class TestWorkflowRun(SimpleTestCase):
    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_resolves_watermark_on_first_iteration(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                ("2026-04-10T00:00:00+00:00", "org-0"),  # get_stripe_watermark_activity
                EnrichStripePageResult(
                    rows_fetched=100,
                    updated=90,
                    skipped_no_account=10,
                    errors=[],
                    next_cursor_last_changed_at="2026-04-12T00:00:00+00:00",
                    next_cursor_org_id="org-99",
                ),
                None,  # commit_stripe_watermark_activity
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500, max_rows=100)
        result = await wf.run(inputs)

        assert mock_workflow.execute_activity.await_count == 3
        assert result["total_rows_fetched"] == 100
        assert result["total_updated"] == 90
        assert result["committed_watermark_ts"] == "2026-04-12T00:00:00+00:00"
        assert result["committed_watermark_org_id"] == "org-99"

        # The first-page activity must receive the prior-run watermark as its
        # starting cursor so the run resumes strictly after that keyset row.
        page_call_args = mock_workflow.execute_activity.await_args_list[1]
        page_inputs = page_call_args.args[1]
        assert page_inputs.cursor_last_changed_at == "2026-04-10T00:00:00+00:00"
        assert page_inputs.cursor_org_id == "org-0"
        mock_workflow.continue_as_new.assert_not_called()

    @pytest.mark.asyncio
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
                    next_cursor_last_changed_at="2026-04-12T00:00:00+00:00",
                    next_cursor_org_id="org-499",
                ),
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500)
        await wf.run(inputs)

        mock_workflow.continue_as_new.assert_called_once()
        call_args = mock_workflow.continue_as_new.call_args[0][0]
        assert call_args.state.cursor_last_changed_at == "2026-04-12T00:00:00+00:00"
        assert call_args.state.cursor_org_id == "org-499"
        assert call_args.state.pending_watermark_ts == "2026-04-12T00:00:00+00:00"
        assert call_args.state.pending_watermark_org_id == "org-499"

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_force_full_refresh_skips_read_but_commits(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                EnrichStripePageResult(
                    rows_fetched=10,
                    updated=10,
                    skipped_no_account=0,
                    errors=[],
                    next_cursor_last_changed_at="2026-04-12T00:00:00+00:00",
                    next_cursor_org_id="org-9",
                ),
                None,  # commit_stripe_watermark_activity
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500, force_full_refresh=True, max_rows=10)
        result = await wf.run(inputs)

        # Force-full-refresh skips the *read* of the prior watermark, but
        # still commits at the end so the next incremental run resumes from
        # where the full refresh finished instead of replaying history.
        assert mock_workflow.execute_activity.await_count == 2
        commit_call = mock_workflow.execute_activity.await_args_list[1]
        commit_inputs = commit_call.args[1]
        assert commit_inputs.last_changed_at == "2026-04-12T00:00:00+00:00"
        assert commit_inputs.posthog_organization_id == "org-9"
        assert result["committed_watermark_ts"] == "2026-04-12T00:00:00+00:00"
        assert result["committed_watermark_org_id"] == "org-9"

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_continuation_uses_stored_cursor(self, mock_workflow):
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                EnrichStripePageResult(
                    rows_fetched=10,
                    updated=10,
                    skipped_no_account=0,
                    errors=[],
                    next_cursor_last_changed_at="2026-04-13T00:00:00+00:00",
                    next_cursor_org_id="org-509",
                ),
                None,  # commit_watermark
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        state = StripeEnrichmentState(
            total_rows_fetched=500,
            total_updated=500,
            pending_watermark_ts="2026-04-12T00:00:00+00:00",
            pending_watermark_org_id="org-499",
            cursor_last_changed_at="2026-04-12T00:00:00+00:00",
            cursor_org_id="org-499",
        )
        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500, state=state, max_rows=510)
        result = await wf.run(inputs)

        # The continuation must pass the stored cursor to the activity and
        # must NOT re-read the prior-run watermark — that only happens on the
        # very first iteration.
        page_call_args = mock_workflow.execute_activity.await_args_list[0]
        page_inputs = page_call_args.args[1]
        assert page_inputs.cursor_last_changed_at == "2026-04-12T00:00:00+00:00"
        assert page_inputs.cursor_org_id == "org-499"

        assert result["total_rows_fetched"] == 510
        assert result["committed_watermark_ts"] == "2026-04-13T00:00:00+00:00"
        assert result["committed_watermark_org_id"] == "org-509"
        mock_workflow.continue_as_new.assert_not_called()

    @pytest.mark.asyncio
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
                    next_cursor_last_changed_at="2026-04-12T00:00:00+00:00",
                    next_cursor_org_id="org-9",
                ),
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500, max_rows=10)
        result = await wf.run(inputs)

        assert result["error_count"] == 15
        assert len(result["errors"]) == 10

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_page_failure_holds_back_committed_watermark(self, mock_workflow):
        """Once a page reports any error, the run must not advance the Redis
        watermark — the next run has to rescan the failed rows, including any
        that tie on ``last_changed_at`` with successfully processed rows."""
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                ("2026-04-01T00:00:00+00:00", "org-a"),  # prior watermark
                EnrichStripePageResult(
                    rows_fetched=3,
                    updated=2,
                    skipped_no_account=0,
                    errors=["sfdc_bulk_update_failed_count=1"],
                    next_cursor_last_changed_at="2026-04-12T00:00:00+00:00",
                    next_cursor_org_id="org-2",
                ),
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500, max_rows=3)
        result = await wf.run(inputs)

        # commit_stripe_watermark_activity must NOT run — only the watermark
        # read is counted against the 2 expected awaits.
        assert mock_workflow.execute_activity.await_count == 2
        assert result["committed_watermark_ts"] is None
        assert result["committed_watermark_org_id"] is None
        assert result["error_count"] == 1

    @pytest.mark.asyncio
    @patch(f"{WORKFLOW_MODULE}.workflow")
    async def test_failure_after_successful_page_freezes_watermark(self, mock_workflow):
        """A later successful page cannot jump the watermark past an earlier
        failing page. The state-carried ``run_has_failures`` flag simulates the
        continue-as-new chain in a single iteration."""
        mock_workflow.execute_activity = AsyncMock(
            side_effect=[
                EnrichStripePageResult(
                    rows_fetched=2,
                    updated=2,
                    skipped_no_account=0,
                    errors=[],
                    next_cursor_last_changed_at="2026-04-20T00:00:00+00:00",
                    next_cursor_org_id="org-z",
                ),
                None,  # commit_watermark
            ]
        )
        mock_workflow.continue_as_new = MagicMock()

        state = StripeEnrichmentState(
            total_rows_fetched=1000,
            total_updated=998,
            error_count=2,
            errors=["earlier page failure"],
            pending_watermark_ts="2026-04-10T00:00:00+00:00",  # last fully-successful page's keyset
            pending_watermark_org_id="org-last-good",
            run_has_failures=True,
            cursor_last_changed_at="2026-04-15T00:00:00+00:00",
            cursor_org_id="org-prev",
        )
        wf = SalesforceStripeEnrichmentWorkflow()
        inputs = StripeEnrichmentInputs(page_size=500, state=state, max_rows=1002)
        result = await wf.run(inputs)

        # Two awaits: the page activity, then commit_stripe_watermark_activity.
        assert mock_workflow.execute_activity.await_count == 2
        # Watermark was committed, but at the earlier successful page's keyset
        # position, NOT this page's — otherwise the next run would skip the
        # failed rows whose (last_changed_at, org_id) sits between the two.
        commit_call = mock_workflow.execute_activity.await_args_list[1]
        commit_inputs = commit_call.args[1]
        assert commit_inputs.last_changed_at == "2026-04-10T00:00:00+00:00"
        assert commit_inputs.posthog_organization_id == "org-last-good"
        assert result["committed_watermark_ts"] == "2026-04-10T00:00:00+00:00"
        assert result["committed_watermark_org_id"] == "org-last-good"
