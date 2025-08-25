from typing import Optional, TypeVar, Union

from django.db import models
from django.db.models import Q
from django.db.models.query import QuerySet, RawQuerySet

from rest_framework import filters, settings
from rest_framework.request import Request
from rest_framework.views import APIView

_MT = TypeVar("_MT", bound=models.Model)


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
                search_filter_query = search_filter_query | Q(**{f"{search_field}__icontains": search_term})
            term_filter = term_filter & search_filter_query

        return queryset.filter(term_filter)


def term_search_filter_sql(
    search_fields: list[str],
    search_terms: Optional[str] = "",
    search_extra: Optional[str] = "",
) -> tuple[str, dict]:
    if not search_fields or not search_terms:
        return "", {}

    terms = list(filter(None, search_terms.replace("\x00", "").split(" ")))

    kwargs = {}
    term_filter = []
    for term_idx, search_term in enumerate(terms):
        search_filter_query = []
        for idx, search_field in enumerate(search_fields):
            index = term_idx * len(search_fields) + idx
            search_filter_query.append(f"{search_field} ilike %(search_{index})s")
            kwargs[f"search_{index}"] = f"%{search_term}%"
        term_filter.append(f"({' OR '.join(search_filter_query)})")

    if term_filter:
        return f"AND (({' AND '.join(term_filter)}) {search_extra})", kwargs
    else:
        return "", {}
