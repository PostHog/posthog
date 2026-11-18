from typing import Optional, TypeVar, Union

from django.db import models
from django.db.models import Q
from django.db.models.query import QuerySet, RawQuerySet

from rest_framework import filters, settings
from rest_framework.request import Request
from rest_framework.views import APIView

_MT = TypeVar("_MT", bound=models.Model)


class PhraseSearchFilter(filters.SearchFilter):
    """Matches `?search=` as one literal substring instead of splitting it into independent terms.

    DRF's SearchFilter ANDs the whitespace-separated parts, so `NON PROD` also matches `Non-prod`.
    """

    def get_search_terms(self, request: Request) -> list[str]:
        term = request.query_params.get(self.search_param, "").replace("\x00", "").strip()
        return [term] if term else []


class TermSearchFilterBackend(filters.BaseFilterBackend):
    """
    Allows fuzzy searching based on the pg_trgm extension.
    Remember to add relevant indices if the table is expected to have large amounts of data.
    """

    # The URL query parameter used for the search.
    search_param = settings.api_settings.SEARCH_PARAM

    def get_search_fields(self, view: APIView) -> Optional[list[str]]:
        """
        Search fields are obtained from the view.
        """
        return getattr(view, "search_fields", None)

    def get_search_terms(self, request: Request):
        """
        Search terms are set by a ?search=... query parameter
        """
        terms = request.query_params.get(self.search_param, "")
        terms = terms.replace("\x00", "")  # strip null characters
        return list(filter(None, terms.split(" ")))

    def filter_queryset(
        self,
        request: Request,
        queryset: Union[QuerySet[_MT], RawQuerySet],
        view: APIView,
    ):
        if isinstance(queryset, RawQuerySet):
            return queryset

        search_fields = self.get_search_fields(view)
        search_terms = self.get_search_terms(request)

        if not search_fields or not search_terms:
            return queryset

        term_filter = Q()
        for _term_idx, search_term in enumerate(search_terms):
            search_filter_query = Q()
            for _idx, search_field in enumerate(search_fields):
                # nosemgrep: orm-field-injection -- search_field from view's get_search_fields(), not user input
                search_filter_query = search_filter_query | Q(**{f"{search_field}__icontains": search_term})
            term_filter = term_filter & search_filter_query

        return queryset.filter(term_filter)


def _trigram_candidate_pattern(term: str) -> str:
    # The pattern only selects candidate rows from the trigram index, and the `strpos` check next to it
    # keeps the rows that contain the literal term. `%` and `_` stay wildcards: an escaped one marks a word
    # boundary, so pg_trgm adds boundary trigrams that occur in many names, and the index scan reads more
    # pages. A backslash must be escaped, because an unescaped one escapes the next character or makes the
    # pattern invalid, and then the pattern no longer matches every row that contains the term.
    return "%" + term.replace("\\", "\\\\") + "%"


def term_search_filter_sql(
    search_fields: list[str],
    search_terms: Optional[str] = "",
    search_extra: Optional[str] = "",
    avoid_trigram_index: bool = False,
) -> tuple[str, dict]:
    """Builds the `?search=` predicate: every space-separated term must appear literally in one of the fields.

    `strpos(lower(field), lower(term)) > 0` does the literal match, and no trigram index can serve it. By
    default a `field ILIKE pattern` condition goes with it, so that the planner can find candidate rows in a
    trigram GIN index on the field. Where that index is global and the query is already scoped to one
    tenant, the planner still often reads the posting lists for the whole index. `avoid_trigram_index`
    emits only the `strpos` check, so the planner has to start from the tenant-scoped index instead.
    """
    if not search_fields or not search_terms:
        return "", {}

    terms = list(filter(None, search_terms.replace("\x00", "").split(" ")))

    kwargs: dict[str, str] = {}
    term_filter = []
    for term_idx, search_term in enumerate(terms):
        kwargs[f"search_term_{term_idx}"] = search_term
        if not avoid_trigram_index:
            kwargs[f"search_pattern_{term_idx}"] = _trigram_candidate_pattern(search_term)
        search_filter_query = []
        for search_field in search_fields:
            contains_term = f"strpos(lower({search_field}), lower(%(search_term_{term_idx})s)) > 0"
            if avoid_trigram_index:
                search_filter_query.append(contains_term)
            else:
                search_filter_query.append(f"({search_field} ilike %(search_pattern_{term_idx})s AND {contains_term})")
        term_filter.append(f"({' OR '.join(search_filter_query)})")

    if term_filter:
        return f"AND (({' AND '.join(term_filter)}) {search_extra})", kwargs
    else:
        return "", {}
