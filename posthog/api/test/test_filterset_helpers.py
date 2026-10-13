from typing import Any

import pytest

from django.db.models import QuerySet
from django.urls import path

import django_filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import OpenApiParameter, extend_schema
from parameterized import parameterized
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.filterset_helpers import FilterParameterOverride, filterset_openapi_parameters, validate_filterset
from posthog.models.health_issue import HealthIssue


class HealthIssueFilterSet(django_filters.FilterSet):
    id = django_filters.UUIDFilter()
    status = django_filters.ChoiceFilter(choices=HealthIssue.Status.choices)
    severity = django_filters.MultipleChoiceFilter(choices=HealthIssue.Severity.choices)
    dismissed = django_filters.BooleanFilter(help_text="Only dismissed issues.")
    created_at = django_filters.DateTimeFromToRangeFilter()
    search = django_filters.CharFilter(method="filter_search", help_text="Matches the issue kind.")

    class Meta:
        model = HealthIssue
        fields: list[str] = []

    def filter_search(self, queryset: QuerySet[HealthIssue], name: str, value: str) -> QuerySet[HealthIssue]:
        return queryset.filter(kind__icontains=value)


class HealthIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = HealthIssue
        fields = ["id"]


class BackendFilteredView(ListAPIView):
    queryset = HealthIssue.objects.none()
    serializer_class = HealthIssueSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = HealthIssueFilterSet
    include_in_api_docs = True


def _view_with_parameters(parameters: list[OpenApiParameter]) -> type[ListAPIView]:
    class ServiceFilteredView(ListAPIView):
        queryset = HealthIssue.objects.none()
        serializer_class = HealthIssueSerializer
        filter_backends: list[type] = []
        include_in_api_docs = True

        @extend_schema(parameters=parameters)
        def get(self, request: Request, *args: Any, **kwargs: Any) -> Any:
            return super().get(request, *args, **kwargs)

    return ServiceFilteredView


def _spec_parameters(view_class: type[ListAPIView]) -> dict[str, dict[str, Any]]:
    generator = SchemaGenerator(patterns=[path("issues/", view_class.as_view())])
    schema = generator.get_schema(request=None, public=True)
    return {parameter["name"]: parameter for parameter in schema["paths"]["/issues/"]["get"]["parameters"]}


def test_parameters_match_the_spec_from_django_filter_backend() -> None:
    expected = _spec_parameters(BackendFilteredView)
    actual = _spec_parameters(_view_with_parameters(filterset_openapi_parameters(HealthIssueFilterSet)))

    assert set(expected) >= {"id", "status", "severity", "dismissed", "created_at_after", "created_at_before", "search"}
    assert actual == expected


def test_exclude_and_overrides_patch_the_emitted_parameters() -> None:
    parameters = filterset_openapi_parameters(
        HealthIssueFilterSet,
        exclude=["created_at_before"],
        overrides={"search": FilterParameterOverride(description="Kind substring.", enum=["a", "b"])},
    )
    spec = _spec_parameters(_view_with_parameters(parameters))

    assert "created_at_before" not in spec
    assert spec["search"]["description"] == "Kind substring."
    assert spec["search"]["schema"]["enum"] == ["a", "b"]


@parameterized.expand(
    [
        ("exclude", {"exclude": ["not_a_filter"]}),
        ("overrides", {"overrides": {"not_a_filter": FilterParameterOverride(description="x")}}),
    ]
)
def test_unknown_parameter_names_raise(_name: str, kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="not_a_filter"):
        filterset_openapi_parameters(HealthIssueFilterSet, **kwargs)


@parameterized.expand(
    [
        ("bad_choice", "status=nope"),
        ("bad_uuid", "id=not-a-uuid"),
        ("bad_multiple_choice", "severity=info&severity=nope"),
        ("bad_range", "created_at_after=yesterday-ish"),
    ]
)
def test_validation_error_matches_django_filter_backend(_name: str, query: str) -> None:
    request = Request(APIRequestFactory().get(f"/issues/?{query}"))
    queryset = HealthIssue.objects.none()

    with pytest.raises(ValidationError) as backend_error:
        DjangoFilterBackend().filter_queryset(request, queryset, BackendFilteredView())
    with pytest.raises(ValidationError) as helper_error:
        validate_filterset(HealthIssueFilterSet, request.query_params, queryset, request=request)

    assert helper_error.value.detail == backend_error.value.detail


def test_valid_query_returns_the_bound_filterset() -> None:
    request = Request(APIRequestFactory().get("/issues/?status=active&dismissed=true"))

    filterset = validate_filterset(
        HealthIssueFilterSet, request.query_params, HealthIssue.objects.none(), request=request
    )

    assert filterset.form.cleaned_data["status"] == "active"
    assert filterset.form.cleaned_data["dismissed"] is True
