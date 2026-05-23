from typing import Any

from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
from django.db.models import F, Q, QuerySet, Value
from django.db.models.functions import Coalesce

from opentelemetry import trace

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


def apply_trigram_search(
    queryset: QuerySet,
    search: str,
    *,
    span_prefix: str,
    extra_word_fields: tuple[str, ...] = (),
    include_tag_search: bool = False,
    extra_tiebreakers: tuple[str, ...] = (),
) -> QuerySet:
    """
    Apply trigram + literal-substring search across `name`, `description`, and any
    `extra_word_fields` (e.g. `derived_name` for insights).

    `name` gets both word and full-string similarity, so an exact name match outranks
    a row that merely contains the search word. `description` gets word similarity
    scaled by `DESCRIPTION_SCORE_WEIGHT`, so a description-only hit ranks below a
    name hit. Extra word fields get unweighted word similarity.

    Word similarity (`<%`) drives match/no-match — it's index-accelerated and handles
    prefix-as-you-type. Literal `icontains` predicates are OR'd in for tokens dense
    with non-alphanumerics (emails, UUIDs, dotted identifiers) where pg_trgm splits
    at punctuation and scores below threshold.

    When `include_tag_search=True`, rows whose tag names contain the search term are
    also returned. `.distinct()` is applied to dedup the tag-join fan-out (a row with
    N matching tags would otherwise appear N times via `Q(id__in=matching_tag_ids)`).

    Nullable name columns are coalesced to 0.0 so a NULL-name row matched only on
    description doesn't end up with a NULL `_search_score` (Postgres orders NULLS
    FIRST in DESC, putting unnamed rows wrongly at the top).
    """
    search = normalize_search_term(search)
    span = trace.get_current_span()
    span.set_attribute(f"{span_prefix}.length", len(search))
    if not search:
        return queryset

    zero = Value(0.0)

    word_annotations: dict[str, Any] = {
        "_name_word": Coalesce(TrigramWordSimilarity(search, "name"), zero),
        "_name_full": Coalesce(TrigramSimilarity("name", search), zero),
        "_description_word": Coalesce(TrigramWordSimilarity(search, "description"), zero),
    }
    for field in extra_word_fields:
        word_annotations[f"_{field}_word"] = Coalesce(TrigramWordSimilarity(search, field), zero)

    threshold_filter = Q(_name_word__gt=MIN_NAME_TRIGRAM_SIMILARITY) | Q(
        _description_word__gt=MIN_DESCRIPTION_TRIGRAM_SIMILARITY
    )
    for field in extra_word_fields:
        threshold_filter |= Q(**{f"_{field}_word__gt": MIN_NAME_TRIGRAM_SIMILARITY})

    icontains_filter = Q(name__icontains=search) | Q(description__icontains=search)
    for field in extra_word_fields:
        icontains_filter |= Q(**{f"{field}__icontains": search})

    combined_filter = threshold_filter | icontains_filter

    if include_tag_search:
        matching_tag_ids = queryset.filter(tagged_items__tag__name__icontains=search).values("id")
        combined_filter |= Q(id__in=matching_tag_ids)

    match_score_annotations: dict[str, Any] = {
        "_name_match_score": F("_name_word") + F("_name_full"),
        "_description_match_score": F("_description_word"),
    }
    for field in extra_word_fields:
        match_score_annotations[f"_{field}_match_score"] = F(f"_{field}_word")

    search_score: Any = F("_name_match_score")
    for field in extra_word_fields:
        search_score = search_score + F(f"_{field}_match_score")
    search_score = search_score + F("_description_match_score") * DESCRIPTION_SCORE_WEIGHT

    order_keys = ("-_search_score", *extra_tiebreakers, "name")

    result = (
        queryset.annotate(**word_annotations)
        .filter(combined_filter)
        .annotate(**match_score_annotations)
        .annotate(_search_score=search_score)
        .order_by(*order_keys)
    )

    if include_tag_search:
        result = result.distinct()

    return result
