"""
FilterSet helpers for views that filter in a service instead of through `DjangoFilterBackend`.

A product facade often owns list filtering and returns contracts, so the view no longer
lists `DjangoFilterBackend` in `filter_backends`. drf-spectacular then drops the filter
query params from the schema, and the backend no longer validates the query string.
These helpers keep both behaviors tied to the FilterSet, so the spec and the 400 body
stay the same as with the backend.
"""

import copy
from collections.abc import Collection, Mapping, Sequence
from typing import Any, TypeVar

from django.db.models import QuerySet

from django_filters import utils as django_filters_utils
from django_filters.rest_framework import DjangoFilterBackend, FilterSet
from drf_spectacular.extensions import OpenApiFilterExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiParameter
from rest_framework.generics import GenericAPIView

from posthog.dataclasses import frozen

FilterSetT = TypeVar("FilterSetT", bound=FilterSet)


@frozen
class FilterParameterOverride:
    """Replaces what drf-spectacular derives for one query param, e.g. for a `method=` filter."""

    description: str | None = None
    enum: Sequence[Any] | None = None


def _build_schema_view(filterset_class: type[FilterSet]) -> GenericAPIView:
    model = filterset_class._meta.model
    if model is None:
        raise ValueError(f"{filterset_class.__name__} needs Meta.model to derive OpenAPI parameters.")

    view_class = type(
        f"{filterset_class.__name__}SchemaView",
        (GenericAPIView,),
        {
            # .none() builds a lazy queryset, so this never queries the database.
            "queryset": model._default_manager.none(),
            "filter_backends": [DjangoFilterBackend],
            "filterset_class": filterset_class,
        },
    )
    return view_class()


def _build_auto_schema(view: GenericAPIView) -> AutoSchema:
    auto_schema = view.schema
    if not isinstance(auto_schema, AutoSchema):
        raise TypeError("DEFAULT_SCHEMA_CLASS must be a drf-spectacular AutoSchema.")
    # Spectacular sets these per operation during generation. The filter extension reads
    # the view, and the warning messages read the method and path.
    auto_schema.method = "GET"
    auto_schema.path = ""
    auto_schema.path_regex = ""
    auto_schema.path_prefix = ""
    return auto_schema


def _to_openapi_parameter(parameter: Mapping[str, Any], override: FilterParameterOverride | None) -> OpenApiParameter:
    schema = copy.deepcopy(parameter["schema"])
    # build_parameter_type puts the enum on the items of an array schema, so read it from there.
    enum_holder = schema["items"] if schema.get("type") == "array" else schema
    enum = enum_holder.pop("enum", None)
    description = parameter.get("description", "")

    if override is not None and override.description is not None:
        description = override.description
    if override is not None and override.enum is not None:
        enum = list(override.enum)

    return OpenApiParameter(
        name=parameter["name"],
        type=schema,
        location=parameter["in"],
        required=parameter.get("required", False),
        description=description,
        enum=enum,
        explode=parameter.get("explode"),
        style=parameter.get("style"),
    )


def filterset_openapi_parameters(
    filterset_class: type[FilterSet],
    *,
    exclude: Collection[str] = (),
    overrides: Mapping[str, FilterParameterOverride] | None = None,
) -> list[OpenApiParameter]:
    """The query params drf-spectacular emits for `filterset_class` under `DjangoFilterBackend`.

    Use as `@extend_schema(parameters=filterset_openapi_parameters(MyFilterSet))` on a view that
    filters in a service. `exclude` and `overrides` take the emitted param names, e.g. `created_at_min`.
    """
    overrides = overrides or {}
    view = _build_schema_view(filterset_class)
    auto_schema = _build_auto_schema(view)
    # Same lookup as AutoSchema._get_filter_parameters, so a registered extension that
    # replaces DjangoFilterExtension applies here too.
    extension = OpenApiFilterExtension.get_match(DjangoFilterBackend())
    if extension is None:
        raise RuntimeError("drf-spectacular has no filter extension for DjangoFilterBackend.")
    raw_parameters: list[dict[str, Any]] = extension.get_schema_operation_parameters(auto_schema)

    emitted_names = {parameter["name"] for parameter in raw_parameters}
    unknown_names = (set(exclude) | set(overrides)) - emitted_names
    if unknown_names:
        raise ValueError(f"{filterset_class.__name__} emits no query params named {sorted(unknown_names)}.")

    return [
        _to_openapi_parameter(parameter, overrides.get(parameter["name"]))
        for parameter in raw_parameters
        if parameter["name"] not in exclude
    ]


def validate_filterset(
    filterset_class: type[FilterSetT],
    query_params: Mapping[str, Any],
    queryset: QuerySet[Any],
    **kwargs: Any,
) -> FilterSetT:
    """Bind `query_params` to `filterset_class` and return it, or raise the 400 that DjangoFilterBackend raises.

    Use in a view that filters in a service: `filterset = validate_filterset(MyFilterSet, request.query_params,
    queryset, request=request)`, then read `filterset.form.cleaned_data` or `filterset.qs`.
    """
    filterset = filterset_class(data=query_params, queryset=queryset, **kwargs)
    if not filterset.is_valid():
        raise django_filters_utils.translate_validation(filterset.errors)
    return filterset
