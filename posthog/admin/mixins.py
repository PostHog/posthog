from django.db import models


class QueryTaggingMixin:
    """
    Mixin to add SQL comment tags to queries originating from Django admin
    """

    query_tag_prefix: str = "django_admin"

    def _get_model_name(self) -> str:
        return self.model._meta.model_name.lower()

    def _add_query_tag(self, queryset: models.QuerySet, operation: str, **kwargs) -> models.QuerySet:
        model_name = self._get_model_name()

        tag_parts = [f"source={self.query_tag_prefix}", f"model={model_name}", f"operation={operation}"]

        for key, value in kwargs.items():
            if value:
                clean_value = str(value).replace("'", "").replace("/*", "").replace("*/", "")[:20]
                tag_parts.append(f"{key}='{clean_value}'")

        tag_comment = "/* " + ",".join(tag_parts) + " */"

        # apparently this is the best way to hack a query tag into a query via the django ORM
        return queryset.extra(where=[f"1=1 {tag_comment}"])

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if request.GET.get("q"):
            operation = "search"
            search_term = request.GET.get("q", "")
            queryset = self._add_query_tag(queryset, operation, term=search_term)
        elif any(key not in ["o", "p", "q"] for key in request.GET.keys()):
            operation = "filter"
            filters = {k: v for k, v in request.GET.items() if k not in ["o", "p", "q"]}
            filter_summary = f"{len(filters)} filters"
            queryset = self._add_query_tag(queryset, operation, filters=filter_summary)
        else:
            operation = "list"
            queryset = self._add_query_tag(queryset, operation)

        return queryset
