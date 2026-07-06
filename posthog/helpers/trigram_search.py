from dataclasses import dataclass
from typing import Any

from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
from django.db.models import Case, F, IntegerField, Q, QuerySet, Value, When
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


@dataclass(frozen=True)
class TrigramSearchField:
    """One field a saved-list search scores and matches against.

    `field` is the ORM lookup path (e.g. `name`, `user__email`). `weight` scales the
    field's word-similarity contribution to `_search_score`. `threshold` is the minimum
    word similarity for the fuzzy match. `include_full` adds full-string similarity to
    the score so an exact-string hit outranks a row that merely contains the word.
    `literal` OR's an `icontains` predicate so substrings dense with non-alphanumerics
    (emails, UUIDs, dotted identifiers) — which pg_trgm tokenizes below threshold — still
    match, labelled `exact`."""

    field: str
    weight: float = 1.0
    threshold: float = MIN_NAME_TRIGRAM_SIMILARITY
    include_full: bool = False
    literal: bool = True

    @property
    def key(self) -> str:
        # Annotation aliases can't contain the `__` lookup separator.
        return self.field.replace("__", "_")


# The common case: a `name` (word + full similarity) and a freeform `description`
# (word similarity only, down-weighted and held to a higher threshold).
NAME_FIELD = TrigramSearchField("name", include_full=True)
DESCRIPTION_FIELD = TrigramSearchField(
    "description", weight=DESCRIPTION_SCORE_WEIGHT, threshold=MIN_DESCRIPTION_TRIGRAM_SIMILARITY
)


def normalize_search_term(search: str) -> str:
    # Postgres rejects NUL bytes in text parameters; strip before they hit the query.
    return search.replace("\x00", "").strip()


def search_match_type_from_instance(instance: Any) -> str | None:
    """Map the `_is_exact` annotation that `apply_trigram_search` leaves on each row to the
    `search_match_type` API value. Null when the list was not filtered by `search` (the
    annotation is absent), `exact` when the term is a literal substring of a searched field,
    `similar` when only the fuzzy trigram path matched."""
    is_exact = getattr(instance, "_is_exact", None)
    if is_exact is None:
        return None
    return "exact" if is_exact else "similar"


def apply_trigram_search(
    queryset: QuerySet,
    search: str,
    *,
    span_prefix: str,
    fields: tuple[TrigramSearchField, ...],
    include_tag_search: bool = False,
    extra_exact_q: Q | None = None,
    tiebreakers: tuple[str, ...] = (),
) -> QuerySet:
    """Apply trigram + literal-substring search across `fields`, returning exact matches only
    unless there are none, in which case fall back to similar matches.

    Two predicates select the rows. The literal `icontains` predicate (`exact_q`) catches
    tokens dense with non-alphanumerics — emails, UUIDs, dotted identifiers — where pg_trgm
    splits at punctuation and scores below threshold. The trigram word-similarity predicate
    (`similar_q`) catches typos and prefix-as-you-type. A row matching `exact_q` is flagged
    `_is_exact=1`.

    Similar (fuzzy-only) matches are suppressed whenever any exact match exists — otherwise,
    once a caller re-orders by e.g. last-modified, similar matches can fill the visible area
    and bury the exact hits the user was looking for. When no exact match exists, the similar
    matches are returned so a typo'd query still finds something.

    `_search_score` ranks rows by each field's weighted word similarity (plus full-string
    similarity where `include_full` is set). `tiebreakers` are appended after the score
    (e.g. `-pinned`, `name`).

    `extra_exact_q` OR's caller-supplied predicates into the exact tier — for structured
    fields that don't fit trigram (a commit-SHA prefix, an exact numeric id). Rows matched
    this way are flagged `_is_exact=1` and sort with the literal-substring matches.

    When `include_tag_search=True`, rows whose tag names contain the term also match (as
    `exact`), and `.distinct()` dedups the tag-join fan-out.

    Word/full annotations are coalesced to 0.0 so a row with a NULL field matched only on
    another field doesn't end up with a NULL `_search_score` (Postgres orders NULLS FIRST in
    DESC, putting such rows wrongly at the top)."""
    search = normalize_search_term(search)
    span = trace.get_current_span()
    span.set_attribute(f"{span_prefix}.length", len(search))
    if not search:
        return queryset

    zero = Value(0.0)

    word_annotations: dict[str, Any] = {}
    for f in fields:
        word_annotations[f"_word_{f.key}"] = Coalesce(TrigramWordSimilarity(search, f.field), zero)
        if f.include_full:
            word_annotations[f"_full_{f.key}"] = Coalesce(TrigramSimilarity(f.field, search), zero)

    exact_q = Q()
    for f in fields:
        if f.literal:
            # nosemgrep: orm-field-injection — f.field is a developer-defined TrigramSearchField path, not user input; only `search` is user-controlled and it is the bound value
            exact_q |= Q(**{f"{f.field}__icontains": search})
    if extra_exact_q is not None:
        exact_q |= extra_exact_q
    if include_tag_search:
        matching_tag_ids = queryset.filter(tagged_items__tag__name__icontains=search).values("id")
        exact_q |= Q(id__in=matching_tag_ids)

    similar_q = Q()
    for f in fields:
        # nosemgrep: orm-field-injection — f.key derives from a developer-defined TrigramSearchField path, not user input
        similar_q |= Q(**{f"_word_{f.key}__gt": f.threshold})

    search_score: Any = None
    for f in fields:
        component: Any = F(f"_word_{f.key}") * f.weight
        if f.include_full:
            component = component + F(f"_full_{f.key}")
        search_score = component if search_score is None else search_score + component

    annotated = queryset.annotate(**word_annotations).annotate(
        _is_exact=Case(When(exact_q, then=Value(1)), default=Value(0), output_field=IntegerField()),
        _search_score=search_score,
    )

    exact_only = annotated.filter(exact_q)

    # Prefer exact matches; only fall back to the fuzzy tier when there are none.
    if exact_only.exists():
        result = exact_only
    else:
        result = annotated.filter(similar_q)

    if include_tag_search:
        result = result.distinct()

    return result.order_by("-_search_score", *tiebreakers)
