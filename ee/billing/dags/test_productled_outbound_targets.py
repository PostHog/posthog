from datetime import datetime
from typing import cast

import pytest
from unittest.mock import MagicMock, patch

import polars as pl
import dagster
from dagster import JsonMetadataValue
from parameterized import parameterized

from ee.billing.dags.productled_outbound_targets import (
    TEAM_PRODUCT_SCHEMA,
    build_team_product_df,
    compute_event_growth,
    compute_multi_product_usage,
    compute_new_product_this_month,
    compute_new_users_30d,
    dataframe_to_plo_clay_payload,
    fetch_org_users,
    filter_qualified,
    get_plo_prior_hashes,
    plo_base_targets,
    plo_daily_schedule,
    plo_qualified_to_clay,
    qualify_signals,
)


def make_base_row(**overrides) -> dict:
    """Create a base row dict with all BASE_COLUMNS, applying overrides."""
    defaults = {
        "business_model": None,
        "company_tags": None,
        "company_type": "startup",
        "domain": "test.com",
        "headcount": 100,
        "headcount_engineering": None,
        "icp_score": None,
        "industry": None,
        "last_3m_avg_mrr": 5000.0,
        "organization_created_at": "2023-01-01",
        "organization_id": "org-1",
        "organization_name": "Test Corp",
        "peak_arr": None,
        "peak_mrr": None,
        "trailing_12m_revenue": None,
        "vitally_churned_at": None,
        "vitally_owner": None,
    }
    defaults.update(overrides)
    return defaults


def make_base_schema() -> dict:
    """Return the schema dict for empty base DataFrames."""
    return {
        "business_model": pl.Utf8,
        "company_tags": pl.Utf8,
        "company_type": pl.Utf8,
        "domain": pl.Utf8,
        "headcount": pl.Int64,
        "headcount_engineering": pl.Int64,
        "icp_score": pl.Int64,
        "industry": pl.Utf8,
        "last_3m_avg_mrr": pl.Float64,
        "organization_created_at": pl.Utf8,
        "organization_id": pl.Utf8,
        "organization_name": pl.Utf8,
        "peak_arr": pl.Float64,
        "peak_mrr": pl.Float64,
        "trailing_12m_revenue": pl.Float64,
        "vitally_churned_at": pl.Utf8,
        "vitally_owner": pl.Utf8,
    }


class TestPloBaseTargets:
    @patch("ee.billing.dags.productled_outbound_targets.execute_hogql_query")
    @patch("ee.billing.dags.productled_outbound_targets.Team")
    def test_returns_dataframe_with_results(self, mock_team, mock_hogql):
        mock_team.objects.get.return_value = MagicMock()
        mock_response = MagicMock()
        # Return a row with all BASE_COLUMNS in order
        mock_response.results = [
            (
                "saas",  # business_model
                "tech",  # company_tags
                "startup",  # company_type
                "acme.com",  # domain
                100,  # headcount
                20,  # headcount_engineering
                75,  # icp_score
                "Software",  # industry
                5000.0,  # last_3m_avg_mrr
                datetime(2023, 1, 1),  # organization_created_at
                "org-1",  # organization_id
                "Acme Inc",  # organization_name
                60000.0,  # peak_arr
                5000.0,  # peak_mrr
                55000.0,  # trailing_12m_revenue
                None,  # vitally_churned_at
                "owner@acme.com",  # vitally_owner
            ),
        ]
        mock_hogql.return_value = mock_response

        context = dagster.build_asset_context()
        df = plo_base_targets(context)

        assert isinstance(df, pl.DataFrame)
        assert len(df) == 1
        assert df["domain"][0] == "acme.com"
        assert df["organization_id"][0] == "org-1"
        mock_team.objects.get.assert_called_once()

    @patch("ee.billing.dags.productled_outbound_targets.execute_hogql_query")
    @patch("ee.billing.dags.productled_outbound_targets.Team")
    def test_returns_empty_dataframe_when_no_results(self, mock_team, mock_hogql):
        mock_team.objects.get.return_value = MagicMock()
        mock_response = MagicMock()
        mock_response.results = []
        mock_hogql.return_value = mock_response

        context = dagster.build_asset_context()
        df = plo_base_targets(context)

        assert isinstance(df, pl.DataFrame)
        assert len(df) == 0


class TestBuildTeamProductDf:
    @patch("ee.billing.dags.productled_outbound_targets.sync_execute")
    def test_builds_team_product_dataframe(self, mock_sync):
        mock_sync.return_value = [
            (1, "org-1", True, False, True, False),
            (2, "org-1", False, True, False, False),
            (3, "org-2", True, True, True, True),
        ]

        df = build_team_product_df(["org-1", "org-2"])

        assert len(df) == 3
        assert set(df.columns) == {
            "team_id",
            "organization_id",
            "session_recording_opt_in",
            "surveys_opt_in",
            "heatmaps_opt_in",
            "autocapture_exceptions_opt_in",
        }

    @patch("ee.billing.dags.productled_outbound_targets.sync_execute")
    def test_returns_empty_for_no_orgs(self, mock_sync):
        mock_sync.return_value = []

        df = build_team_product_df([])

        assert len(df) == 0


class TestComputeMultiProductUsage:
    @parameterized.expand(
        [
            (
                "three_products_one_org",
                pl.DataFrame(
                    {
                        "team_id": [1, 2],
                        "organization_id": ["org-1", "org-1"],
                        "session_recording_opt_in": [True, False],
                        "surveys_opt_in": [False, True],
                        "heatmaps_opt_in": [True, False],
                        "autocapture_exceptions_opt_in": [False, False],
                    }
                ),
                {"org-1": 3},
            ),
            (
                "zero_products",
                pl.DataFrame(
                    {
                        "team_id": [1],
                        "organization_id": ["org-1"],
                        "session_recording_opt_in": [False],
                        "surveys_opt_in": [False],
                        "heatmaps_opt_in": [False],
                        "autocapture_exceptions_opt_in": [False],
                    }
                ),
                {"org-1": 0},
            ),
            (
                "one_product_across_teams",
                pl.DataFrame(
                    {
                        "team_id": [1, 2],
                        "organization_id": ["org-1", "org-1"],
                        "session_recording_opt_in": [True, True],
                        "surveys_opt_in": [False, False],
                        "heatmaps_opt_in": [False, False],
                        "autocapture_exceptions_opt_in": [False, False],
                    }
                ),
                {"org-1": 1},
            ),
        ]
    )
    def test_multi_product_count(self, name, team_df, expected):
        result = compute_multi_product_usage(team_df)
        for org_id, count in expected.items():
            assert result.get(org_id, 0) == count


class TestComputeEventGrowth:
    @parameterized.expand(
        [
            (
                "growth_above_30pct",
                [(1, 1000, 500)],
                pl.DataFrame({"team_id": [1], "organization_id": ["org-1"]}),
                {"org-1": 100.0},
            ),
            (
                "no_events",
                [],
                pl.DataFrame({"team_id": [1], "organization_id": ["org-1"]}),
                {},
            ),
            (
                "decline",
                [(1, 200, 500)],
                pl.DataFrame({"team_id": [1], "organization_id": ["org-1"]}),
                {"org-1": -60.0},
            ),
            (
                "new_org_zero_prior",
                [(1, 500, 0)],
                pl.DataFrame({"team_id": [1], "organization_id": ["org-1"]}),
                {"org-1": None},
            ),
            (
                "multiple_teams_same_org",
                [(1, 300, 200), (2, 400, 100)],
                pl.DataFrame({"team_id": [1, 2], "organization_id": ["org-1", "org-1"]}),
                {"org-1": pytest.approx(133.33, abs=0.01)},
            ),
        ]
    )
    @patch("ee.billing.dags.productled_outbound_targets.execute_hogql_query")
    @patch("ee.billing.dags.productled_outbound_targets.Team")
    def test_event_growth(self, name, hogql_results, team_df, expected, mock_team, mock_hogql):
        mock_team.objects.get.return_value = MagicMock()
        mock_response = MagicMock()
        mock_response.results = hogql_results
        mock_hogql.return_value = mock_response

        result = compute_event_growth(team_df)

        for org_id, val in expected.items():
            assert result[org_id] == val


class TestComputeNewUsers30d:
    @parameterized.expand(
        [
            ("no_new_users", [], {}),
            ("two_new_users", [("org-1", 2)], {"org-1": 2}),
            ("multiple_orgs", [("org-1", 3), ("org-2", 1)], {"org-1": 3, "org-2": 1}),
        ]
    )
    @patch("ee.billing.dags.productled_outbound_targets.OrganizationMembership")
    def test_new_users(self, name, queryset_result, expected, mock_membership):
        mock_qs = MagicMock()
        mock_membership.objects.filter.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.annotate.return_value = [
            {"organization_id": org_id, "new_user_count": count} for org_id, count in queryset_result
        ]

        result = compute_new_users_30d(["org-1", "org-2"])

        assert result == expected


class TestFetchOrgUsers:
    @patch("ee.billing.dags.productled_outbound_targets.OrganizationMembership")
    def test_returns_users_grouped_by_org(self, mock_membership):
        mock_qs = MagicMock()
        mock_membership.objects.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.values_list.return_value = [
            ("org-1", "Alice", "Smith", "alice@acme.com", datetime(2023, 1, 15)),
            ("org-1", "Bob", "Jones", "bob@acme.com", datetime(2023, 3, 1)),
            ("org-2", "Carol", "Lee", "carol@beta.io", None),
        ]

        result = fetch_org_users(["org-1", "org-2"])

        assert len(result["org-1"]) == 2
        assert result["org-1"][0] == {
            "first_name": "Alice",
            "last_name": "Smith",
            "email": "alice@acme.com",
            "joined_at": "2023-01-15T00:00:00",
        }
        assert result["org-2"][0]["joined_at"] is None

    @patch("ee.billing.dags.productled_outbound_targets.OrganizationMembership")
    def test_returns_empty_dict_for_no_members(self, mock_membership):
        mock_qs = MagicMock()
        mock_membership.objects.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.values_list.return_value = []

        result = fetch_org_users(["org-1"])

        assert result == {}

    def test_returns_empty_dict_for_empty_org_ids(self):
        result = fetch_org_users([])

        assert result == {}


class TestComputeNewProductThisMonth:
    @parameterized.expand(
        [
            (
                "new_product_detected",
                [(1, "$snapshot", 50, 0)],
                pl.DataFrame(
                    {
                        "team_id": [1],
                        "organization_id": ["org-1"],
                        "session_recording_opt_in": [True],
                        "surveys_opt_in": [False],
                        "heatmaps_opt_in": [False],
                        "autocapture_exceptions_opt_in": [False],
                    }
                ),
                {"org-1": "session_recording"},
            ),
            (
                "existing_product_not_new",
                [(1, "$snapshot", 50, 30)],
                pl.DataFrame(
                    {
                        "team_id": [1],
                        "organization_id": ["org-1"],
                        "session_recording_opt_in": [True],
                        "surveys_opt_in": [False],
                        "heatmaps_opt_in": [False],
                        "autocapture_exceptions_opt_in": [False],
                    }
                ),
                {},
            ),
            (
                "flag_off_ignored",
                [(1, "$snapshot", 50, 0)],
                pl.DataFrame(
                    {
                        "team_id": [1],
                        "organization_id": ["org-1"],
                        "session_recording_opt_in": [False],
                        "surveys_opt_in": [False],
                        "heatmaps_opt_in": [False],
                        "autocapture_exceptions_opt_in": [False],
                    }
                ),
                {},
            ),
            (
                "multiple_new_products",
                [(1, "$snapshot", 10, 0), (1, "survey sent", 5, 0)],
                pl.DataFrame(
                    {
                        "team_id": [1],
                        "organization_id": ["org-1"],
                        "session_recording_opt_in": [True],
                        "surveys_opt_in": [True],
                        "heatmaps_opt_in": [False],
                        "autocapture_exceptions_opt_in": [False],
                    }
                ),
                {"org-1": "session_recording,surveys"},
            ),
        ]
    )
    @patch("ee.billing.dags.productled_outbound_targets.execute_hogql_query")
    @patch("ee.billing.dags.productled_outbound_targets.Team")
    def test_new_product(self, name, hogql_results, team_df, expected, mock_team, mock_hogql):
        mock_team.objects.get.return_value = MagicMock()
        mock_response = MagicMock()
        mock_response.results = hogql_results
        mock_hogql.return_value = mock_response

        result = compute_new_product_this_month(team_df)

        assert result == expected


class TestFilterQualified:
    @parameterized.expand(
        [
            (
                "passes_multi_product",
                {"multi_product_count": 2, "event_growth_pct": 0.0, "new_user_count": 0, "new_products": ""},
                True,
            ),
            (
                "passes_event_growth",
                {"multi_product_count": 0, "event_growth_pct": 50.0, "new_user_count": 0, "new_products": ""},
                True,
            ),
            (
                "passes_new_users",
                {"multi_product_count": 0, "event_growth_pct": 0.0, "new_user_count": 3, "new_products": ""},
                True,
            ),
            (
                "passes_new_product",
                {
                    "multi_product_count": 0,
                    "event_growth_pct": 0.0,
                    "new_user_count": 0,
                    "new_products": "session_recording",
                },
                True,
            ),
            (
                "fails_all_criteria",
                {"multi_product_count": 1, "event_growth_pct": 10.0, "new_user_count": 1, "new_products": ""},
                False,
            ),
        ]
    )
    def test_filter_qualified(self, name, row_data, should_pass):
        row = make_base_row(**row_data)
        df = pl.DataFrame([row])

        result = filter_qualified(df)

        if should_pass:
            assert len(result) == 1
        else:
            assert len(result) == 0


class TestDataframeToPloClayPayload:
    def test_converts_to_payload_with_users(self):
        row = make_base_row(
            domain="acme.com",
            organization_id="org-1",
            organization_name="Acme Inc",
        )
        row.update(
            {
                "multi_product_count": 3,
                "event_growth_pct": 50.0,
                "new_user_count": 2,
                "new_products": "session_recording",
            }
        )
        df = pl.DataFrame([row])
        org_users = {
            "org-1": [
                {
                    "first_name": "Alice",
                    "last_name": "Smith",
                    "email": "alice@acme.com",
                    "joined_at": "2023-01-15T00:00:00",
                },
            ]
        }

        payload = dataframe_to_plo_clay_payload(df, org_users)

        assert len(payload) == 1
        assert payload[0]["domain"] == "acme.com"
        assert payload[0]["multi_product_count"] == 3
        assert payload[0]["event_growth_pct"] == 50.0
        assert payload[0]["new_user_count"] == 2
        assert payload[0]["new_products"] == "session_recording"
        assert payload[0]["users"] == org_users["org-1"]

    def test_converts_to_payload_with_no_users(self):
        row = make_base_row(
            domain="acme.com",
            organization_id="org-1",
            organization_name="Acme Inc",
        )
        row.update(
            {
                "multi_product_count": 3,
                "event_growth_pct": 50.0,
                "new_user_count": 2,
                "new_products": "session_recording",
            }
        )
        df = pl.DataFrame([row])

        payload = dataframe_to_plo_clay_payload(df, {})

        assert len(payload) == 1
        assert payload[0]["users"] == []


class TestPloQualifiedToClay:
    @patch("ee.billing.dags.productled_outbound_targets.fetch_org_users")
    @patch("ee.billing.dags.productled_outbound_targets.get_plo_prior_hashes")
    def test_sends_changed_rows_to_clay(self, mock_prior_hashes, mock_fetch_users):
        mock_prior_hashes.return_value = {}
        mock_fetch_users.return_value = {
            "org-1": [{"first_name": "Alice", "last_name": "Smith", "email": "alice@acme.com", "joined_at": None}]
        }

        context = dagster.build_asset_context()
        clay_webhook = MagicMock()
        batch_result = MagicMock()
        batch_result.batches = [[{"domain": "acme.com"}]]
        batch_result.truncated_count = 0
        batch_result.skipped_count = 0
        clay_webhook.create_batches.return_value = batch_result

        row = make_base_row(
            domain="acme.com",
            organization_id="org-1",
            organization_name="Acme Inc",
        )
        row.update(
            {
                "multi_product_count": 3,
                "event_growth_pct": 50.0,
                "new_user_count": 2,
                "new_products": "session_recording",
            }
        )
        enriched_df = pl.DataFrame([row])

        plo_qualified_to_clay(context, clay_webhook, enriched_df)

        clay_webhook.create_batches.assert_called_once()
        payload = clay_webhook.create_batches.call_args[0][0]
        assert payload[0]["users"] == mock_fetch_users.return_value["org-1"]
        clay_webhook.send.assert_called_once()

    @patch("ee.billing.dags.productled_outbound_targets.fetch_org_users")
    @patch("ee.billing.dags.productled_outbound_targets.get_plo_prior_hashes")
    def test_skips_unchanged_rows(self, mock_prior_hashes, mock_fetch_users):
        from posthog.dags.common.utils import compute_dataframe_hashes

        row = make_base_row(
            domain="acme.com",
            organization_id="org-1",
            organization_name="Acme Inc",
        )
        row.update(
            {
                "multi_product_count": 3,
                "event_growth_pct": 50.0,
                "new_user_count": 2,
                "new_products": "session_recording",
            }
        )
        enriched_df = pl.DataFrame([row])

        # Pre-compute the hash so the row appears unchanged
        qualified = filter_qualified(enriched_df)
        hashed = compute_dataframe_hashes(qualified)
        prior = {
            row["organization_id"]: row["data_hash"]
            for row in hashed.select(["organization_id", "data_hash"]).to_dicts()
        }
        mock_prior_hashes.return_value = prior

        context = dagster.build_asset_context()
        clay_webhook = MagicMock()

        plo_qualified_to_clay(context, clay_webhook, enriched_df)

        clay_webhook.send.assert_not_called()
        mock_fetch_users.assert_not_called()

    @patch("ee.billing.dags.productled_outbound_targets.get_plo_prior_hashes")
    def test_filters_unqualified_rows(self, mock_prior_hashes):
        mock_prior_hashes.return_value = {}

        context = dagster.build_asset_context()
        clay_webhook = MagicMock()

        row = make_base_row(
            domain="loser.com",
            headcount=10,
            company_type="smb",
            organization_id="org-x",
            organization_name="Loser Co",
            organization_created_at="2023-06-01",
        )
        row.update(
            {
                "multi_product_count": 1,
                "event_growth_pct": 5.0,
                "new_user_count": 0,
                "new_products": "",
            }
        )
        enriched_df = pl.DataFrame([row])

        plo_qualified_to_clay(context, clay_webhook, enriched_df)

        clay_webhook.send.assert_not_called()


class TestGetPloPriorHashes:
    def test_returns_empty_dict_when_no_prior_event(self):
        context = MagicMock()
        context.instance.get_latest_materialization_event.return_value = None

        result = get_plo_prior_hashes(context)

        assert result == {}

    def test_returns_empty_dict_when_no_materialization(self):
        event = MagicMock()
        event.asset_materialization = None
        context = MagicMock()
        context.instance.get_latest_materialization_event.return_value = event

        result = get_plo_prior_hashes(context)

        assert result == {}

    def test_returns_empty_dict_when_metadata_missing(self):
        mat = MagicMock()
        mat.metadata = {}
        event = MagicMock()
        event.asset_materialization = mat
        context = MagicMock()
        context.instance.get_latest_materialization_event.return_value = event

        result = get_plo_prior_hashes(context)

        assert result == {}

    def test_returns_hashes_from_metadata(self):
        expected = {"org-1": "abc123", "org-2": "def456"}
        mat = MagicMock()
        mat.metadata = {"org_hashes": JsonMetadataValue(data=expected)}
        event = MagicMock()
        event.asset_materialization = mat
        context = MagicMock()
        context.instance.get_latest_materialization_event.return_value = event

        result = get_plo_prior_hashes(context)

        assert result == expected

    def test_returns_empty_dict_when_metadata_wrong_type(self):
        mat = MagicMock()
        mat.metadata = {"org_hashes": "not_a_json_metadata_value"}
        event = MagicMock()
        event.asset_materialization = mat
        context = MagicMock()
        context.instance.get_latest_materialization_event.return_value = event

        result = get_plo_prior_hashes(context)

        assert result == {}


class TestQualifySignals:
    @patch("ee.billing.dags.productled_outbound_targets.compute_new_product_this_month")
    @patch("ee.billing.dags.productled_outbound_targets.compute_new_users_30d")
    @patch("ee.billing.dags.productled_outbound_targets.compute_event_growth")
    @patch("ee.billing.dags.productled_outbound_targets.compute_multi_product_usage")
    @patch("ee.billing.dags.productled_outbound_targets.build_team_product_df")
    def test_enriches_base_targets_with_signals(self, mock_team_df, mock_multi, mock_growth, mock_users, mock_product):
        mock_team_df.return_value = pl.DataFrame(schema=TEAM_PRODUCT_SCHEMA)
        mock_multi.return_value = {"org-1": 3, "org-2": 1}
        mock_growth.return_value = {"org-1": 50.0, "org-2": -10.0}
        mock_users.return_value = {"org-1": 5}
        mock_product.return_value = {"org-1": "session_recording"}

        row1 = make_base_row(
            domain="acme.com",
            headcount=100,
            company_type="startup",
            organization_id="org-1",
            organization_name="Acme",
            organization_created_at="2023-01-01",
        )
        row2 = make_base_row(
            domain="beta.io",
            headcount=50,
            company_type="smb",
            organization_id="org-2",
            organization_name="Beta",
            organization_created_at="2023-06-01",
        )
        base_df = pl.DataFrame([row1, row2])

        context = dagster.build_asset_context()
        result = cast(pl.DataFrame, qualify_signals(context, base_df))

        assert len(result) == 2
        assert "multi_product_count" in result.columns
        assert "event_growth_pct" in result.columns
        assert "new_user_count" in result.columns
        assert "new_products" in result.columns

        row_1 = result.filter(pl.col("organization_id") == "org-1").to_dicts()[0]
        assert row_1["multi_product_count"] == 3
        assert row_1["event_growth_pct"] == 50.0
        assert row_1["new_user_count"] == 5
        assert row_1["new_products"] == "session_recording"

        row_2 = result.filter(pl.col("organization_id") == "org-2").to_dicts()[0]
        assert row_2["multi_product_count"] == 1
        assert row_2["event_growth_pct"] == -10.0
        assert row_2["new_user_count"] == 0
        assert row_2["new_products"] == ""

    def test_returns_empty_with_signal_columns_when_no_base_targets(self):
        base_df = pl.DataFrame(schema=make_base_schema())

        context = dagster.build_asset_context()
        result = cast(pl.DataFrame, qualify_signals(context, base_df))

        assert len(result) == 0
        assert "multi_product_count" in result.columns
        assert "event_growth_pct" in result.columns
        assert "new_user_count" in result.columns
        assert "new_products" in result.columns


class TestFilterQualifiedBoundaries:
    @parameterized.expand(
        [
            (
                "event_growth_at_boundary_30_fails",
                {"multi_product_count": 0, "event_growth_pct": 30.0, "new_user_count": 0, "new_products": ""},
                False,
            ),
            (
                "event_growth_just_above_boundary_passes",
                {"multi_product_count": 0, "event_growth_pct": 30.1, "new_user_count": 0, "new_products": ""},
                True,
            ),
            (
                "new_user_count_at_boundary_2_passes",
                {"multi_product_count": 0, "event_growth_pct": 0.0, "new_user_count": 2, "new_products": ""},
                True,
            ),
            (
                "new_user_count_below_boundary_1_fails",
                {"multi_product_count": 0, "event_growth_pct": 0.0, "new_user_count": 1, "new_products": ""},
                False,
            ),
            (
                "multi_product_at_boundary_2_passes",
                {"multi_product_count": 2, "event_growth_pct": 0.0, "new_user_count": 0, "new_products": ""},
                True,
            ),
            (
                "multi_product_below_boundary_1_fails",
                {"multi_product_count": 1, "event_growth_pct": 0.0, "new_user_count": 0, "new_products": ""},
                False,
            ),
        ]
    )
    def test_filter_qualified_boundary(self, name, row_data, should_pass):
        row = make_base_row(**row_data)
        df = pl.DataFrame([row])

        result = filter_qualified(df)

        if should_pass:
            assert len(result) == 1
        else:
            assert len(result) == 0


class TestEmptyDataFramePaths:
    def test_compute_event_growth_empty_dataframe(self):
        empty_df = pl.DataFrame(schema={"team_id": pl.Int64, "organization_id": pl.Utf8})
        result = compute_event_growth(empty_df)
        assert result == {}

    def test_compute_new_product_this_month_empty_dataframe(self):
        empty_df = pl.DataFrame(schema=TEAM_PRODUCT_SCHEMA)
        result = compute_new_product_this_month(empty_df)
        assert result == {}

    @patch("ee.billing.dags.productled_outbound_targets.OrganizationMembership")
    def test_compute_new_users_30d_empty_org_ids(self, mock_membership):
        result = compute_new_users_30d([])
        assert result == {}
        mock_membership.objects.filter.assert_not_called()

    def test_dataframe_to_plo_clay_payload_empty_dataframe(self):
        schema = make_base_schema()
        schema.update(
            {
                "multi_product_count": pl.Int64,
                "event_growth_pct": pl.Float64,
                "new_user_count": pl.Int64,
                "new_products": pl.Utf8,
            }
        )
        df = pl.DataFrame(schema=schema)

        payload = dataframe_to_plo_clay_payload(df, {})

        assert payload == []


class TestPloDailySchedule:
    def test_returns_run_request(self):
        context = dagster.build_schedule_context()
        result = plo_daily_schedule(context)

        assert isinstance(result, dagster.RunRequest)
