import json
from datetime import UTC, datetime
from typing import Any

import pytest

import polars as pl

from ee.billing.dags.customer_archetype import (
    SF_DATETIME_FORMAT,
    AccountClassification,
    _query_recently_classified_ids,
    apply_deterministic_archetype,
    build_salesforce_records,
    compute_use_case_adoption,
    parse_llm_response,
    prepare_llm_batches,
)

# --------------------------------------------------------------------------- #
# Test helpers
# --------------------------------------------------------------------------- #


def _make_account_row(**overrides: Any) -> dict:
    """Build a single account row dict with sensible defaults."""
    defaults: dict[str, Any] = {
        "sf_account_id": "001ABC",
        "name": "Acme Corp",
        "posthog_organization_id": "org-123",
        "harmonic_industry_c": "Saas",
        "founded_year_c": 2018,
        "number_of_employees": 200,
        "harmonic_headcount_c": 180,
        "harmonic_headcount_engineering_c": 40,
        "pct_engineers_c": 22,
        "harmonic_is_yc_company_c": False,
        "tech_tag_c": "mixpanel;segment",
        "harmonic_funding_stage_c": "SERIES_B",
        "harmonic_total_funding_c": 50_000_000,
        "total_funding_raised_c": 50_000_000,
        "billing_country": "United States",
        "business_model_c": None,
        "clearbit_business_model_c": None,
        "clay_industry_c": None,
        "has_llm_analytics": 0,
        "distinct_products_used": 4,
        # MRR columns
        "latest_product_analytics_mrr": 300.0,
        "latest_surveys_mrr": 0.0,
        "latest_web_analytics_mrr_est": 50.0,
        "latest_posthog_ai_mrr": 0.0,
        "latest_feature_flags_mrr": 150.0,
        "latest_session_replay_mrr": 200.0,
        "latest_mobile_replay_mrr": 0.0,
        "latest_error_tracking_mrr": 0.0,
        "latest_logs_mrr": 0.0,
        "latest_llm_analytics_mrr": 0.0,
        "latest_data_warehouse_mrr": 0.0,
        "latest_data_pipelines_mrr": 0.0,
        "latest_batch_exports_mrr": 0.0,
        "latest_realtime_destinations_mrr": 0.0,
    }
    defaults.update(overrides)
    return defaults


def _make_account_df(**overrides: Any) -> pl.DataFrame:
    """Build a single-row Polars DataFrame with account defaults."""
    return pl.DataFrame([_make_account_row(**overrides)])


def _make_multi_account_df(rows: list[dict]) -> pl.DataFrame:
    """Build a multi-row DataFrame from a list of override dicts."""
    return pl.DataFrame([_make_account_row(**r) for r in rows])


# --------------------------------------------------------------------------- #
# Stage 3: compute_use_case_adoption
# --------------------------------------------------------------------------- #


class TestComputeUseCaseAdoption:
    def test_product_intelligence_sums_correct_columns(self):
        df = _make_account_df(
            latest_product_analytics_mrr=200.0,
            latest_surveys_mrr=100.0,
            latest_web_analytics_mrr_est=150.0,
            latest_posthog_ai_mrr=60.0,
        )
        result = compute_use_case_adoption(df)
        # 200 + 100 + 150 + 60 = 510 → Significant
        assert result["uc_product_intelligence"][0] == "Significant"

    def test_release_engineering_single_column(self):
        df = _make_account_df(latest_feature_flags_mrr=75.0)
        result = compute_use_case_adoption(df)
        assert result["uc_release_eng"][0] == "Experimental"

    def test_observability_sums_four_columns(self):
        df = _make_account_df(
            latest_session_replay_mrr=100.0,
            latest_mobile_replay_mrr=50.0,
            latest_error_tracking_mrr=200.0,
            latest_logs_mrr=200.0,
        )
        result = compute_use_case_adoption(df)
        # 100 + 50 + 200 + 200 = 550 → Significant
        assert result["uc_observability"][0] == "Significant"

    def test_ai_llm_observability(self):
        df = _make_account_df(latest_llm_analytics_mrr=250.0)
        result = compute_use_case_adoption(df)
        assert result["uc_ai_llm_obs"][0] == "Adopted"

    def test_data_infrastructure_sums_four_columns(self):
        df = _make_account_df(
            latest_data_warehouse_mrr=200.0,
            latest_data_pipelines_mrr=100.0,
            latest_batch_exports_mrr=50.0,
            latest_realtime_destinations_mrr=200.0,
        )
        result = compute_use_case_adoption(df)
        # 200 + 100 + 50 + 200 = 550 → Significant
        assert result["uc_data_infra"][0] == "Significant"

    def test_use_case_count_counts_adopted_and_above(self):
        df = _make_account_df(
            # Product Intelligence: 300 + 0 + 50 + 0 = 350 → Adopted ✓
            latest_product_analytics_mrr=300.0,
            latest_surveys_mrr=0.0,
            latest_web_analytics_mrr_est=50.0,
            latest_posthog_ai_mrr=0.0,
            # Release Eng: 150 → Adopted ✓
            latest_feature_flags_mrr=150.0,
            # Observability: 200 → Adopted ✓
            latest_session_replay_mrr=200.0,
            latest_mobile_replay_mrr=0.0,
            latest_error_tracking_mrr=0.0,
            latest_logs_mrr=0.0,
            # AI/LLM Obs: 0 → None ✗
            latest_llm_analytics_mrr=0.0,
            # Data Infra: 0 → None ✗
            latest_data_warehouse_mrr=0.0,
            latest_data_pipelines_mrr=0.0,
            latest_batch_exports_mrr=0.0,
            latest_realtime_destinations_mrr=0.0,
        )
        result = compute_use_case_adoption(df)
        assert result["use_case_count"][0] == 3

    def test_all_none_when_no_mrr(self):
        zero_overrides = dict.fromkeys(
            [
                "latest_product_analytics_mrr",
                "latest_surveys_mrr",
                "latest_web_analytics_mrr_est",
                "latest_posthog_ai_mrr",
                "latest_feature_flags_mrr",
                "latest_session_replay_mrr",
                "latest_mobile_replay_mrr",
                "latest_error_tracking_mrr",
                "latest_logs_mrr",
                "latest_llm_analytics_mrr",
                "latest_data_warehouse_mrr",
                "latest_data_pipelines_mrr",
                "latest_batch_exports_mrr",
                "latest_realtime_destinations_mrr",
            ],
            0.0,
        )
        df = _make_account_df(**zero_overrides)
        result = compute_use_case_adoption(df)

        assert result["uc_product_intelligence"][0] == "None"
        assert result["uc_release_eng"][0] == "None"
        assert result["uc_observability"][0] == "None"
        assert result["uc_ai_llm_obs"][0] == "None"
        assert result["uc_data_infra"][0] == "None"
        assert result["use_case_count"][0] == 0


# --------------------------------------------------------------------------- #
# Stage 4: LLM classification helpers
# --------------------------------------------------------------------------- #


class TestPrepareLLMBatches:
    def test_batches_accounts_by_size(self):
        rows = [_make_account_row(sf_account_id=f"00{i}") for i in range(45)]
        df = pl.DataFrame(rows)
        batches = prepare_llm_batches(df, batch_size=20)
        assert len(batches) == 3
        assert len(batches[0]) == 20
        assert len(batches[1]) == 20
        assert len(batches[2]) == 5

    def test_single_batch_when_under_limit(self):
        df = _make_account_df()
        batches = prepare_llm_batches(df, batch_size=20)
        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_omits_null_fields(self):
        df = _make_account_df(business_model_c=None, clay_industry_c=None)
        batches = prepare_llm_batches(df, batch_size=20)
        account = batches[0][0]
        assert "business_model_c" not in account
        assert "clay_industry_c" not in account

    def test_excludes_non_context_columns(self):
        df = _make_account_df()
        batches = prepare_llm_batches(df, batch_size=20)
        account = batches[0][0]
        # MRR columns and posthog_organization_id should not be in LLM context
        assert "latest_product_analytics_mrr" not in account
        assert "posthog_organization_id" not in account
        # sf_account_id should be included (LLM echoes it back)
        assert "sf_account_id" in account


class TestParseLLMResponse:
    def test_parses_valid_response(self):
        raw = json.dumps(
            {
                "classifications": [
                    {
                        "sf_account_id": "001ABC",
                        "archetype": "Cloud Native",
                        "ai_native_score": 2,
                        "cloud_native_score": 6,
                        "stage": "Scaled",
                        "key_signals": "SaaS company founded 2018 with analytics tools in tech stack.",
                    }
                ]
            }
        )
        results = parse_llm_response(raw)
        assert len(results) == 1
        assert results[0].archetype == "Cloud Native"
        assert results[0].ai_native_score == 2
        assert results[0].cloud_native_score == 6
        assert results[0].stage == "Scaled"
        assert results[0].key_signals == "SaaS company founded 2018 with analytics tools in tech stack."

    def test_returns_empty_on_invalid_json(self):
        results = parse_llm_response("not valid json")
        assert results == []

    def test_deterministic_archetype_from_scores(self):
        classifications = [
            AccountClassification(
                sf_account_id="001",
                archetype="Unknown",  # LLM label ignored
                ai_native_score=5,
                cloud_native_score=1,
                stage="Early / Growth",
                key_signals="AI startup.",
            ),
            AccountClassification(
                sf_account_id="002",
                archetype="Unknown",  # LLM label ignored
                ai_native_score=1,
                cloud_native_score=3,
                stage="Scaled",
                key_signals="SaaS company.",
            ),
            AccountClassification(
                sf_account_id="003",
                archetype="AI Native",  # LLM label ignored
                ai_native_score=1,
                cloud_native_score=1,
                stage="Unknown",
                key_signals="Sparse data.",
            ),
            AccountClassification(
                sf_account_id="004",
                archetype="Cloud Native",  # LLM label ignored — tie-break to AI Native
                ai_native_score=4,
                cloud_native_score=4,
                stage="Early / Growth",
                key_signals="Ambiguous signals.",
            ),
        ]
        result = apply_deterministic_archetype(classifications)
        assert result[0].archetype == "AI Native"
        assert result[1].archetype == "Cloud Native"
        assert result[2].archetype == "Unknown"
        assert result[3].archetype == "AI Native"  # tie-break


# --------------------------------------------------------------------------- #
# Stage 5: Salesforce record construction
# --------------------------------------------------------------------------- #


class TestBuildSalesforceRecords:
    def test_constructs_all_11_fields(self):
        classifications = [
            AccountClassification(
                sf_account_id="001ABC",
                archetype="Cloud Native",
                ai_native_score=2,
                cloud_native_score=6,
                stage="Scaled",
                key_signals="SaaS founded 2018.",
            )
        ]
        use_case_df = compute_use_case_adoption(_make_account_df())

        records = build_salesforce_records(classifications, use_case_df)
        assert len(records) == 1
        rec = records[0]
        assert rec["Id"] == "001ABC"
        assert rec["customer_archetype__c"] == "Cloud Native"
        assert rec["customer_ai_native_score__c"] == 2
        assert rec["customer_cloud_native_score__c"] == 6
        assert rec["customer_stage__c"] == "Scaled"
        assert rec["customer_archetype_key_signals__c"] == "SaaS founded 2018."
        assert "customer_use_case_product_intelligence__c" in rec
        assert "customer_use_case_release_eng__c" in rec
        assert "customer_use_case_observability__c" in rec
        assert "customer_use_case_ai_llm_obs__c" in rec
        assert "customer_use_case_data_infra__c" in rec
        assert "customer_use_case_count__c" in rec

    def test_skips_accounts_missing_from_use_case_data(self):
        classifications = [
            AccountClassification(
                sf_account_id="MISSING",
                archetype="Unknown",
                ai_native_score=0,
                cloud_native_score=0,
                stage="Unknown",
                key_signals="No data.",
            )
        ]
        use_case_df = compute_use_case_adoption(_make_account_df(sf_account_id="001ABC"))
        records = build_salesforce_records(classifications, use_case_df)
        # Should still produce a record but with None use case fields
        assert len(records) == 1
        assert records[0]["customer_use_case_product_intelligence__c"] is None


# --------------------------------------------------------------------------- #
# MRR boundary values
# --------------------------------------------------------------------------- #


class TestUseCaseAdoptionBoundaries:
    @pytest.mark.parametrize(
        "mrr,expected",
        [
            (0, "None"),
            (0.01, "Experimental"),
            (99.99, "Experimental"),
            (100, "Adopted"),
            (499.99, "Adopted"),
            (500, "Significant"),
            (10_000, "Significant"),
        ],
    )
    def test_mrr_boundary_values(self, mrr: float, expected: str):
        df = _make_account_df(latest_feature_flags_mrr=mrr)
        result = compute_use_case_adoption(df)
        assert result["uc_release_eng"][0] == expected

    def test_null_mrr_treated_as_zero(self):
        df = _make_account_df(latest_feature_flags_mrr=None)
        result = compute_use_case_adoption(df)
        assert result["uc_release_eng"][0] == "None"


# --------------------------------------------------------------------------- #
# SF timestamp-based incremental logic
# --------------------------------------------------------------------------- #


class TestQueryRecentlyClassifiedIds:
    def test_returns_ids_from_sf_response(self):
        mock_sf = type("SF", (), {"query_all": lambda self, soql: {"records": [{"Id": "001"}, {"Id": "002"}]}})()
        result = _query_recently_classified_ids(mock_sf, datetime(2026, 3, 1, tzinfo=UTC))
        assert result == {"001", "002"}

    def test_returns_empty_when_no_records(self):
        mock_sf = type("SF", (), {"query_all": lambda self, soql: {"records": []}})()
        result = _query_recently_classified_ids(mock_sf, datetime(2026, 3, 1, tzinfo=UTC))
        assert result == set()

    def test_soql_uses_sf_datetime_format(self):
        captured_soql = []

        class MockSF:
            def query_all(self, soql):
                captured_soql.append(soql)
                return {"records": []}

        cutoff = datetime(2026, 3, 15, 5, 30, 0, tzinfo=UTC)
        _query_recently_classified_ids(MockSF(), cutoff)
        expected_timestamp = cutoff.strftime(SF_DATETIME_FORMAT)
        assert expected_timestamp in captured_soql[0]
        assert "customer_archetype_classified_at__c" in captured_soql[0]


# --------------------------------------------------------------------------- #
# SF datetime format
# --------------------------------------------------------------------------- #


class TestSFDatetimeFormat:
    def test_format_produces_salesforce_compatible_string(self):
        dt = datetime(2026, 3, 15, 14, 30, 45, tzinfo=UTC)
        formatted = dt.strftime(SF_DATETIME_FORMAT)
        assert formatted == "2026-03-15T14:30:45.000+0000"

    def test_format_zero_pads_correctly(self):
        dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        formatted = dt.strftime(SF_DATETIME_FORMAT)
        assert formatted == "2026-01-02T03:04:05.000+0000"


# --------------------------------------------------------------------------- #
# Mega-batch chunking logic
# --------------------------------------------------------------------------- #


class TestMegaBatchChunking:
    """Tests the chunking logic extracted from prepare_and_fan_out."""

    @pytest.mark.parametrize(
        "n_accounts,mega_batch_size,expected_chunks",
        [
            (10, 1000, 1),
            (1000, 1000, 1),
            (1001, 1000, 2),
            (2500, 1000, 3),
            (0, 1000, 0),
        ],
    )
    def test_mega_batch_count(self, n_accounts: int, mega_batch_size: int, expected_chunks: int):
        rows = [_make_account_row(sf_account_id=f"00{i}") for i in range(n_accounts)]
        chunks = [rows[i : i + mega_batch_size] for i in range(0, len(rows), mega_batch_size)]
        assert len(chunks) == expected_chunks

    def test_all_accounts_present_across_chunks(self):
        rows = [_make_account_row(sf_account_id=f"00{i}") for i in range(2500)]
        mega_batch_size = 1000
        chunks = [rows[i : i + mega_batch_size] for i in range(0, len(rows), mega_batch_size)]
        all_ids = {row["sf_account_id"] for chunk in chunks for row in chunk}
        assert len(all_ids) == 2500

    def test_last_chunk_contains_remainder(self):
        rows = [_make_account_row(sf_account_id=f"00{i}") for i in range(2500)]
        mega_batch_size = 1000
        chunks = [rows[i : i + mega_batch_size] for i in range(0, len(rows), mega_batch_size)]
        assert len(chunks[0]) == 1000
        assert len(chunks[1]) == 1000
        assert len(chunks[2]) == 500


# --------------------------------------------------------------------------- #
# Incremental filtering logic
# --------------------------------------------------------------------------- #


class TestIncrementalFiltering:
    """Tests the filtering logic that skips recently classified accounts."""

    def test_filters_out_recently_classified_ids(self):
        df = _make_multi_account_df(
            [
                {"sf_account_id": "001"},
                {"sf_account_id": "002"},
                {"sf_account_id": "003"},
            ]
        )
        recently_classified = {"001", "003"}
        filtered = df.filter(~pl.col("sf_account_id").is_in(recently_classified))
        assert len(filtered) == 1
        assert filtered["sf_account_id"][0] == "002"

    def test_no_filtering_when_no_recent_ids(self):
        df = _make_multi_account_df(
            [
                {"sf_account_id": "001"},
                {"sf_account_id": "002"},
            ]
        )
        filtered = df.filter(~pl.col("sf_account_id").is_in(set()))
        assert len(filtered) == 2

    def test_all_filtered_when_all_recent(self):
        df = _make_multi_account_df(
            [
                {"sf_account_id": "001"},
                {"sf_account_id": "002"},
            ]
        )
        recently_classified = {"001", "002"}
        filtered = df.filter(~pl.col("sf_account_id").is_in(recently_classified))
        assert filtered.is_empty()

    def test_extra_ids_in_recent_set_are_ignored(self):
        df = _make_multi_account_df(
            [
                {"sf_account_id": "001"},
                {"sf_account_id": "002"},
            ]
        )
        # "999" is in the recently_classified set but not in our data — should not cause errors
        recently_classified = {"001", "999"}
        filtered = df.filter(~pl.col("sf_account_id").is_in(recently_classified))
        assert len(filtered) == 1
        assert filtered["sf_account_id"][0] == "002"


# --------------------------------------------------------------------------- #
# classify_and_push_mega_batch: SF record stamping
# --------------------------------------------------------------------------- #


class TestSFRecordTimestampStamping:
    """Verifies that build_salesforce_records output gets the classified_at timestamp applied."""

    def test_records_get_classified_at_timestamp(self):
        classifications = [
            AccountClassification(
                sf_account_id="001ABC",
                archetype="AI Native",
                ai_native_score=5,
                cloud_native_score=1,
                stage="Scaled",
                key_signals="AI startup.",
            )
        ]
        use_case_df = compute_use_case_adoption(_make_account_df())
        records = build_salesforce_records(classifications, use_case_df)

        classified_at = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC).strftime(SF_DATETIME_FORMAT)
        for record in records:
            record["customer_archetype_classified_at__c"] = classified_at

        assert records[0]["customer_archetype_classified_at__c"] == "2026-03-15T10:00:00.000+0000"
        # Original fields are preserved
        assert records[0]["Id"] == "001ABC"
        assert records[0]["customer_archetype__c"] == "AI Native"

    def test_all_records_in_batch_get_same_timestamp(self):
        classifications = [
            AccountClassification(
                sf_account_id=f"00{i}",
                archetype="Unknown",
                ai_native_score=0,
                cloud_native_score=0,
                stage="Unknown",
                key_signals="test",
            )
            for i in range(5)
        ]
        records = build_salesforce_records(classifications, pl.DataFrame())

        classified_at = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC).strftime(SF_DATETIME_FORMAT)
        for record in records:
            record["customer_archetype_classified_at__c"] = classified_at

        timestamps = {r["customer_archetype_classified_at__c"] for r in records}
        assert len(timestamps) == 1


# --------------------------------------------------------------------------- #
# SF query resilience
# --------------------------------------------------------------------------- #


class TestSFQueryResilience:
    def test_sf_exception_propagates_to_caller(self):
        class BrokenSF:
            def query_all(self, soql):
                raise ConnectionError("SF is down")

        # SF failures must propagate — prepare_and_fan_out should fail fast rather
        # than burn LLM credits when classifications can't be persisted to SF.
        with pytest.raises(ConnectionError):
            _query_recently_classified_ids(BrokenSF(), datetime(2026, 1, 1, tzinfo=UTC))
