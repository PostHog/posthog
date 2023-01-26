import json

from django.http import HttpResponse, JsonResponse
from rest_framework import viewsets
from rest_framework.request import Request
from warlock import model_factory

from posthog.api.routing import StructuredViewSetMixin
from posthog.exceptions import RequestParsingError
from posthog.models.filters.mixins.utils import cached_property


class QueryViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    def list(self, request: Request, **kw) -> HttpResponse:
        query_param = self._extract_query_param(request)
        query = self._query_model(query_param)

        if query.kind == "EventsQuery":
            return JsonResponse({"success": "Query is valid!", "query": query})
        else:
            raise RequestParsingError("Invalid query kind: %s" % query.kind)

    def _extract_query_param(self, request):
        if request.method == "POST":
            if request.content_type in ["", "text/plain", "application/json"]:
                query_source = request.body
            else:
                query_source = request.POST.get("query")
        else:
            query_source = request.GET.get("query")

        if query_source is None:
            raise RequestParsingError("Please provide a query in the request body or as a query parameter.")

        try:
            # parse_constant gets called in case of NaN, Infinity etc
            # default behaviour is to put those into the DB directly
            # but we just want it to return None
            query = json.loads(query_source, parse_constant=lambda x: None)
        except (json.JSONDecodeError, UnicodeDecodeError) as error_main:
            raise RequestParsingError("Invalid JSON: %s" % (str(error_main)))
        return query

    @cached_property
    def _json_schema(self):
        with open("frontend/src/queries/schema.json") as f:
            return json.load(f)

    @cached_property
    def _query_model(self):
        return model_factory(self._json_schema)
