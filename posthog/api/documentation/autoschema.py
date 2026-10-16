"""drf-spectacular AutoSchema, mock request and authentication extension wiring."""

import os
import copy
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import models

from drf_spectacular.contrib.rest_framework_dataclasses import OpenApiDataclassSerializerExtensions
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import ComponentRegistry, build_basic_type, build_mock_request, build_parameter_type
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework_dataclasses.fields import EnumField as DataclassEnumField

from posthog.enums import LabeledEnumType
from posthog.permissions import APIScopePermission

# Path parameters that are resolved at runtime by TeamAndOrgViewSetMixin and
# therefore cannot be derived from any model field.  We pre-supply their
# OpenAPI types so drf-spectacular never falls through to the warning path.
_KNOWN_PATH_PARAMS: dict[str, dict[str, Any]] = {
    "project_id": {"schema": build_basic_type(OpenApiTypes.STR), "description": ""},
    "environment_id": {"schema": build_basic_type(OpenApiTypes.STR), "description": ""},
    "organization_id": {"schema": build_basic_type(OpenApiTypes.STR), "description": ""},
    "plugin_config_id": {"schema": build_basic_type(OpenApiTypes.INT), "description": ""},
}


class _FallbackSerializer(serializers.Serializer):
    """Fallback ``serializer_class`` for ViewSets whose methods declare their own
    ``@extend_schema``.  The component name "Fallback" is valid OpenAPI and will
    never appear in the final spec because no endpoint references it."""

    pass


def _include_internal_operations() -> bool:
    return os.environ.get("OPENAPI_INCLUDE_INTERNAL", "").lower() in ("1", "true")


class PostHogAutoSchema(AutoSchema):
    """AutoSchema subclass that silences path-parameter warnings for params
    handled by TeamAndOrgViewSetMixin (project_id, environment_id, etc.)."""

    def is_excluded(self) -> bool:
        if super().is_excluded():
            return True
        # `x-internal` keeps an operation out of the served schema (Swagger, Redoc, the public
        # API docs) but in the codegen build, so MCP tools and frontend types still cover it
        # without a public REST contract.
        return bool(self.get_extensions().get("x-internal")) and not _include_internal_operations()

    def get_operation(
        self, path: str, path_regex: str, path_prefix: str, method: str, registry: ComponentRegistry
    ) -> dict[str, Any] | None:
        operation = super().get_operation(path, path_regex, path_prefix, method, registry)
        # The marker is set here and not in get_extensions(), because an @extend_schema(extensions=...)
        # decorator on the action replaces the get_extensions() output.
        dynamic_actions: frozenset[str] = getattr(self.view, "request_dependent_scope_actions", frozenset())
        if operation is not None and getattr(self.view, "action", None) in dynamic_actions:
            operation["x-request-dependent-scopes"] = True
        return operation

    def _resolve_path_parameters(self, variables):
        from drf_spectacular.plumbing import get_view_model, resolve_django_path_parameter, resolve_regex_path_parameter

        model = get_view_model(self.view, emit_warnings=False)
        parameters = []

        for variable in variables:
            if variable in _KNOWN_PATH_PARAMS:
                # Params handled by TeamAndOrgViewSetMixin — not derivable from any model.
                parameters.append(
                    build_parameter_type(
                        name=variable,
                        location=OpenApiParameter.PATH,
                        description=_KNOWN_PATH_PARAMS[variable]["description"],
                        schema=_KNOWN_PATH_PARAMS[variable]["schema"],
                    )
                )
            elif model is None:
                # No queryset — try to resolve from the URL pattern (e.g. <int:id>),
                # otherwise default to string without warning. Method-level
                # @extend_schema(parameters=...) provides the proper type per-endpoint.
                schema: dict[str, Any] = build_basic_type(OpenApiTypes.STR) or {"type": "string"}
                resolved = resolve_django_path_parameter(
                    self.path_regex,
                    variable,
                    self.map_renderers("format"),
                )
                if not resolved:
                    resolved = resolve_regex_path_parameter(self.path_regex, variable)
                if resolved and (resolved_schema := resolved.get("schema")) is not None:
                    schema = resolved_schema
                parameters.append(
                    build_parameter_type(
                        name=variable,
                        location=OpenApiParameter.PATH,
                        description="",
                        schema=schema,
                    )
                )
            else:
                # Has a model — let the parent derive type + description from the PK field.
                parameters.extend(super()._resolve_path_parameters([variable]))

        return parameters


def build_openapi_mock_request(method, path, view, original_request, **kwargs):
    request = build_mock_request(method, path, view, original_request, **kwargs)

    if os.getenv("OPENAPI_MOCK_INTERNAL_API_SECRET") == "1":
        from django.conf import settings

        request.META["HTTP_X_INTERNAL_API_SECRET"] = settings.INTERNAL_API_SECRET

    return request


def _use_class_labels(field: serializers.Field) -> None:
    child = getattr(field, "child", None)
    if isinstance(child, serializers.Field):
        _use_class_labels(child)
    if not isinstance(field, DataclassEnumField) or field.by_name:
        return
    enum_class = field.enum_class
    if not (isinstance(enum_class, LabeledEnumType) or issubclass(enum_class, models.Choices)):
        return
    # Leave choices that a declared field or extra_kwargs set on purpose.
    library_default = {field.to_representation(member): member.name for member in enum_class}
    if dict(field.choices) == library_default:
        field.choices = enum_class.choices


# rest_framework_dataclasses labels enum choices with member names, which no class carries, so
# posthog/openapi/enum_names.py cannot name those enums after their class. This fixes the schema only.
class LabeledEnumDataclassSerializerExtension(OpenApiDataclassSerializerExtensions):
    priority = 1

    def map_serializer(self, auto_schema: AutoSchema, direction: Any) -> dict[str, Any]:
        # drf-spectacular reuses instances passed to extend_schema, so map a copy. A shallow copy keeps
        # partial=True on PATCH bodies, and dropping the cached fields gives the copy fresh ones.
        serializer = copy.copy(self.target)
        serializer.__dict__.pop("fields", None)
        for field in serializer.fields.values():
            _use_class_labels(field)
        schema = auto_schema._map_serializer(serializer, direction, bypass_extensions=True)
        return self.strip_library_doc(schema)


class PersonalAPIKeyScheme(OpenApiAuthenticationExtension):
    target_class = "posthog.auth.PersonalAPIKeyAuthentication"
    name = "PersonalAPIKeyAuth"

    def get_security_requirement(self, auto_schema):
        view = auto_schema.view
        request = view.request

        for permission in auto_schema.view.get_permissions():
            if isinstance(permission, APIScopePermission):
                try:
                    scopes = permission._get_required_scopes(request, view)
                    if not scopes:
                        return []
                    return [{self.name: scopes}]
                except (PermissionDenied, ImproperlyConfigured):
                    # NOTE: This should never happen - it indicates that we shouldn't be including it in the docs
                    pass

        # Return empty array if no scopes found
        return []

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer"}
