"""Tests for backfill materialized property activities."""

import pytest

from posthog.temporal.backfill_materialized_property.activities import _generate_property_extraction_sql


@pytest.mark.django_db(transaction=True)
class TestPropertyExtractionSQL:
    def test_property_extraction_sql_generation(self):
        sql = _generate_property_extraction_sql()
        # SQL must:
        #   - use the same JSONExtractRaw + nullIf-empty + nullIf-'null' shape as the HogQL
        #     printer's `_unsafe_json_extract_trim_quotes` and plugin-server's
        #     `jsonExtractRawAndTrimQuotes` — see the parity fixture for the contract,
        #   - parameterize property_name (we don't allow user-supplied keys to be inlined
        #     because property names contain quotes / slashes / etc).
        assert "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, %(property_name)s)" in sql
        assert "'null')" in sql
        assert "%(property_name)s" in sql
