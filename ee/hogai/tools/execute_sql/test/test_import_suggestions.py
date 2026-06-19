from parameterized import parameterized

from ee.hogai.tools.execute_sql.import_suggestions import (
    build_import_suggestion,
    extract_unknown_tables,
    suggest_sources_for_table,
)


class TestExtractUnknownTables:
    @parameterized.expand(
        [
            ("none", "Some other error", []),
            ("single", "Unknown table `charges`.", ["charges"]),
            ("with_suggestion_suffix", "Unknown table `charge`. Did you mean: charges?", ["charge"]),
            (
                "multiple_dedup",
                "Unknown table `charges`. Unknown table `charges`. Unknown table `deals`.",
                ["charges", "deals"],
            ),
            ("lowercase_unknown", "unknown table `orders`.", ["orders"]),
        ]
    )
    def test_extract(self, _name: str, message: str, expected: list[str]) -> None:
        assert extract_unknown_tables(message) == expected


class TestSuggestSourcesForTable:
    @parameterized.expand(
        [
            ("charges", "Stripe"),
            ("subscriptions", "Stripe"),
            ("stripe_charges", "Stripe"),
            ("deals", "Hubspot"),
            ("tickets", "Zendesk"),
            ("campaigns", "GoogleAds"),
            ("orders", "Shopify"),
        ]
    )
    def test_known_tables_match(self, table: str, expected_source: str) -> None:
        matched_sources = {s for sources, _ in suggest_sources_for_table(table) for s in sources}
        assert expected_source in matched_sources

    def test_unknown_table_has_no_match(self) -> None:
        assert suggest_sources_for_table("widgets_xyz") == []


class TestBuildImportSuggestion:
    def test_none_when_no_tables(self) -> None:
        assert build_import_suggestion([], set()) is None

    def test_suggests_stripe_for_revenue_table(self) -> None:
        result = build_import_suggestion(["charges"], set())
        assert result is not None
        assert "data-warehouse-source-setup" in result
        assert "Stripe" in result
        assert "<data_import_suggestion>" in result

    def test_generic_fallback_for_unknown_table(self) -> None:
        result = build_import_suggestion(["widgets_xyz"], set())
        assert result is not None
        assert "Postgres" in result

    def test_does_not_resuggest_existing_source_type(self) -> None:
        # Stripe already connected: don't push Stripe again, but flag the existing prefix note.
        result = build_import_suggestion(["charges"], {"Stripe"})
        assert result is not None
        assert "already has these source types" in result
        assert "Stripe" in result
        # Chargebee is still a fresh suggestion for revenue.
        assert "Chargebee" in result
