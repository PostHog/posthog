import datetime as dt

from unittest import TestCase
from unittest.mock import MagicMock, patch

from django.conf import settings

from ee.billing.salesforce_enrichment.duckgres_client import DuckgresNotConfiguredError
from ee.billing.salesforce_enrichment.stripe_signals import _FETCH_QUERY, StripeSignals, fetch_stripe_signals


def _candidate_cte_body(query: str) -> str:
    """Return the SQL body of the ``changed_billing_customer_ids`` CTE.

    Located by name and bracket-matched so assertions about the candidate
    set don't accidentally match predicates lifted from elsewhere in the
    query (e.g. the keyset filter at the bottom).
    """
    marker = "changed_billing_customer_ids AS ("
    start = query.index(marker) + len(marker)
    depth = 1
    i = start
    while depth > 0:
        ch = query[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    return query[start : i - 1]


def _row(
    org_id: str = "org-1",
    stripe_id: str | None = "cus_1",
    synced_at: dt.datetime | None = None,
) -> dict:
    return {
        "posthog_organization_id": org_id,
        "billing_customer_id": "bc-1",
        "billing_customer_name": "Acme Inc",
        "stripe_customer_id": stripe_id,
        "address_line_1": "1 Main St",
        "address_line_2": None,
        "address_city": "San Francisco",
        "address_state": "CA",
        "address_postal_code": "94107",
        "address_country": "US",
        "last_changed_at": synced_at or dt.datetime(2026, 4, 10, 12, 0, tzinfo=dt.UTC),
    }


class TestFetchQueryFilters(TestCase):
    def test_keeps_only_primary_customer_mappings(self):
        assert "cts.primary = TRUE" in _FETCH_QUERY

    def test_excludes_soft_deleted_stripe_customers(self):
        assert "COALESCE(sc.is_deleted, FALSE) = FALSE" in _FETCH_QUERY

    def test_filters_out_rows_without_posthog_organization(self):
        assert "bc.organization_id IS NOT NULL" in _FETCH_QUERY

    def test_applies_keyset_cursor(self):
        # The query is driven purely by the keyset cursor — both the prior-run
        # watermark and intra-run pagination use the same tuple comparison so
        # ``last_changed_at`` ties are handled correctly.
        assert "last_changed_at > %(cursor_ts)s" in _FETCH_QUERY
        assert "posthog_organization_id > %(cursor_org_id)s" in _FETCH_QUERY

    def test_last_changed_at_includes_all_three_source_sync_times(self):
        # ``last_changed_at`` has to reflect the sync time of every source row
        # that can mutate independently: the billing_customer row, the stripe
        # customer row, and the mapping itself. A primary-mapping swap only
        # touches the mapping; if ``mapping_synced_at`` weren't in the
        # ``GREATEST`` the change would sit below the watermark forever.
        assert "sc._fivetran_synced" in _FETCH_QUERY
        assert "pc.billing_customer_synced_at" in _FETCH_QUERY
        assert "pc.mapping_synced_at" in _FETCH_QUERY

    def test_candidate_cte_pushes_cursor_into_each_source_table(self):
        # The candidate CTE is what makes the query incremental: each source's
        # ``_fivetran_synced`` is compared against the cursor directly inside
        # the candidate CTE, so DuckLake can prune parquet files older than
        # the cursor instead of scanning the full join and filtering after
        # the fact. Asserting against the CTE body (not the whole query)
        # guards against regressions that move the predicate elsewhere — for
        # example, hoisting it into the keyset filter would still match a
        # whole-query substring check but would not enable file pruning.
        cte = _candidate_cte_body(_FETCH_QUERY)

        assert "billing_public.billing_customer bc" in cte
        assert "bc._fivetran_synced >= %(cursor_ts)s" in cte

        assert "billing_public.billing_customertostripecustomer cts" in cte
        assert "cts._fivetran_synced >= %(cursor_ts)s" in cte

        assert "ducklake.stripe.customer sc" in cte
        assert "sc._fivetran_synced >= %(cursor_ts)s" in cte

    def test_candidate_cte_falls_back_to_full_scan_when_cursor_is_null(self):
        # First-run / force-full-refresh paths pass ``cursor_ts=NULL``. Each
        # source predicate has to short-circuit so the union returns every
        # eligible row, not zero rows.
        cte = _candidate_cte_body(_FETCH_QUERY)
        assert cte.count("%(cursor_ts)s::timestamptz IS NULL") == 3


class TestStripeSignalsDataClass(TestCase):
    def test_basic_instantiation(self):
        now = dt.datetime(2026, 4, 10, tzinfo=dt.UTC)
        signals = StripeSignals(
            posthog_organization_id="org-1",
            billing_customer_id="bc-1",
            billing_customer_name="Acme",
            stripe_customer_id="cus_1",
            address_line_1="1 Main St",
            address_line_2=None,
            address_city="SF",
            address_state="CA",
            address_postal_code="94107",
            address_country="US",
            last_changed_at=now,
        )

        assert signals.posthog_organization_id == "org-1"
        assert signals.last_changed_at == now


class TestFetchStripeSignals(TestCase):
    @patch.object(settings, "DUCKGRES_PG_URL", None, create=True)
    def test_raises_when_not_configured(self):
        with self.assertRaises(DuckgresNotConfiguredError):
            fetch_stripe_signals(limit=100)

    @patch.object(settings, "DUCKGRES_PG_URL", "postgresql://user:pass@host/db", create=True)
    @patch("ee.billing.salesforce_enrichment.stripe_signals.duckgres_cursor")
    def test_full_backfill_passes_none_cursor(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [_row(org_id="org-1"), _row(org_id="org-2")]
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        result = fetch_stripe_signals(limit=500)

        assert len(result) == 2
        assert result[0].posthog_organization_id == "org-1"
        assert result[1].posthog_organization_id == "org-2"

        executed_params = mock_cursor.execute.call_args[0][1]
        assert executed_params["cursor_ts"] is None
        assert executed_params["cursor_org_id"] is None
        assert executed_params["limit"] == 500

    @patch.object(settings, "DUCKGRES_PG_URL", "postgresql://user:pass@host/db", create=True)
    @patch("ee.billing.salesforce_enrichment.stripe_signals.duckgres_cursor")
    def test_keyset_cursor_passed_through(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        cursor_ts = dt.datetime(2026, 4, 12, 10, 0, tzinfo=dt.UTC)
        fetch_stripe_signals(limit=100, cursor=(cursor_ts, "org-42"))

        executed_params = mock_cursor.execute.call_args[0][1]
        assert executed_params["cursor_ts"] == cursor_ts
        assert executed_params["cursor_org_id"] == "org-42"

    @patch.object(settings, "DUCKGRES_PG_URL", "postgresql://user:pass@host/db", create=True)
    @patch("ee.billing.salesforce_enrichment.stripe_signals.duckgres_cursor")
    def test_returns_empty_list_when_no_rows(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        assert fetch_stripe_signals(limit=100) == []

    @patch.object(settings, "DUCKGRES_PG_URL", "postgresql://user:pass@host/db", create=True)
    @patch("ee.billing.salesforce_enrichment.stripe_signals.duckgres_cursor")
    def test_maps_all_address_fields(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "posthog_organization_id": "org-1",
                "billing_customer_id": "bc-1",
                "billing_customer_name": "Acme",
                "stripe_customer_id": "cus_1",
                "address_line_1": "1 Main St",
                "address_line_2": "Suite 200",
                "address_city": "SF",
                "address_state": "CA",
                "address_postal_code": "94107",
                "address_country": "US",
                "last_changed_at": dt.datetime(2026, 4, 10, tzinfo=dt.UTC),
            }
        ]
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        result = fetch_stripe_signals(limit=100)

        assert len(result) == 1
        s = result[0]
        assert s.address_line_1 == "1 Main St"
        assert s.address_line_2 == "Suite 200"
        assert s.address_city == "SF"
        assert s.address_state == "CA"
        assert s.address_postal_code == "94107"
        assert s.address_country == "US"
