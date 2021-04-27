from typing import List, Optional

from django.contrib.postgres.search import TrigramSimilarity
from django.db import models
from django.db.models.query import QuerySet
from rest_framework import filters, settings
from rest_framework.request import Request
from rest_framework.views import APIView


class FuzzySearchFilterBackend(filters.BaseFilterBackend):
    """
    Allows fuzzy searching based on the pg_trgm extension.
    Remember to add relevant indices if the table is expected to have large amounts of data.
    """

    # The URL query parameter used for the search.
    search_param = settings.api_settings.SEARCH_PARAM

    def get_search_fields(self, view: APIView) -> Optional[List[str]]:
        """
        Search fields are obtained from the view.
        """
        return getattr(view, "search_fields", None)

    def get_fuzzy_search_threshold(self, view: APIView) -> float:
        """
        Get locally configured threshold for search.
        """
        return getattr(view, "search_threshold", 0.3)

    def get_search_terms(self, request: Request):
        """
        Search terms are set by a ?search=... query parameter
        """
        params = request.query_params.get(self.search_param, "")
        params = params.replace("\x00", "")  # strip null characters
        return params

    def filter_queryset(
        self, request: Request, queryset: QuerySet[models.Model], view: APIView,
    ) -> QuerySet[models.Model]:

        search_fields = self.get_search_fields(view)
        search_terms = self.get_search_terms(request)
        search_threshold = self.get_fuzzy_search_threshold(view)

        if not search_fields or not search_terms:
            return queryset

        for idx, search_field in enumerate(search_fields):
            queryset = (
                queryset.annotate(**{f"similarity_{idx}": TrigramSimilarity(search_field, search_terms)})
                .filter(**{f"similarity_{idx}__gte": search_threshold})
                .order_by(f"-similarity_{idx}")
            )

        return queryset
