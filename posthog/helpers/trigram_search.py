# Minimum trigram word similarity for a name match. Calibrated against the
# `test_list_filter_by_search_*` tests in posthog/api/test/dashboards/test_dashboard.py.
# Tighten it and typo cases stop matching, loosen it and unrelated rows leak in.
MIN_NAME_TRIGRAM_SIMILARITY = 0.3
# Description thresholds run higher because descriptions are freeform prose where short
# queries (3-5 chars) can clear a 0.3 threshold against any sufficiently long passage.
MIN_DESCRIPTION_TRIGRAM_SIMILARITY = 0.4
# Description matches contribute less than name matches to the relevance score so that
# a row matched only on description ranks below a row matched on name.
DESCRIPTION_SCORE_WEIGHT = 0.5
# Hard cap on the `?search=` query parameter — protects against pathological inputs
# burning CPU on trigram comparisons against a long string. Both `Dashboard.name` and
# `Insight.name` are bounded at 400 chars so 200 covers any realistic prefix-as-you-type.
MAX_SEARCH_LENGTH = 200


def normalize_search_term(search: str) -> str:
    # Postgres rejects NUL bytes in text parameters; strip before they hit the query.
    return search.replace("\x00", "").strip()
