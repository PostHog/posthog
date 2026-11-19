"""DRF fields that reference an integration row. Not in `posthog.integrations`, so the SDK does not load DRF."""

from collections.abc import Iterable
from typing import Any, Literal

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.fields import empty, get_attribute
from rest_framework.relations import PKOnlyObject

from posthog.integrations.contracts import IntegrationNotFound, IntegrationRecord
from posthog.integrations.enums import AuthType
from posthog.integrations.manager import IntegrationManager


@extend_schema_field(OpenApiTypes.INT)
class IntegrationReferenceField(serializers.Field):
    """An integration id of the request's team. Use it instead of a `PrimaryKeyRelatedField` on `Integration`.

    It reads the team from the serializer context (`team_id`, or `get_team`), so a row of another team
    is "does not exist". Pass `kinds` to accept only rows of these catalogue kinds. The field refuses
    warehouse source rows, the same as `IntegrationManager.any` and `IntegrationManager.kinds(...)`.

    With `kinds`, `auth_types` selects the auth types the field accepts. The default (None) accepts only
    the default auth type of each kind, because code that reads a kind expects its usual config shape.
    Pass a list of auth types, or `"any"` for every auth type. Without `kinds`, the field accepts every row.
    """

    default_error_messages = {
        "does_not_exist": 'Invalid pk "{pk_value}" - object does not exist.',
        "incorrect_type": "Incorrect type. Expected pk value, received {data_type}.",
        "no_team": "The serializer context has no team.",
    }

    def __init__(
        self,
        *,
        kinds: Iterable[str] = (),
        auth_types: Iterable[AuthType] | Literal["any"] | None = None,
        **kwargs: Any,
    ) -> None:
        self.kinds = frozenset(kinds)
        if not self.kinds:
            if auth_types is not None:
                raise ValueError("IntegrationReferenceField needs kinds to filter by auth type")
            self._rows = IntegrationManager.any
        else:
            self._rows = IntegrationManager.kinds(
                *sorted(self.kinds), auth_types="default" if auth_types is None else auth_types
            )
        super().__init__(**kwargs)

    def _team_id(self) -> int:
        team_id = self.context.get("team_id")
        if team_id is None and "get_team" in self.context:
            team_id = self.context["get_team"]().id
        if team_id is None:
            self.fail("no_team")
        return int(team_id)

    def run_validation(self, data: object = empty) -> object:
        # Same as DRF's `RelatedField`: an empty string means no row, so `allow_null` and `required` decide.
        if data == "":
            data = None
        return super().run_validation(data)

    def to_internal_value(self, data: object) -> IntegrationRecord:
        if isinstance(data, bool) or not isinstance(data, int | str):
            self.fail("incorrect_type", data_type=type(data).__name__)
        try:
            integration_id = int(data)
        except ValueError:
            self.fail("incorrect_type", data_type=type(data).__name__)
        try:
            return self._rows.get(self._team_id(), integration_id)
        except IntegrationNotFound:
            self.fail("does_not_exist", pk_value=data)

    def get_attribute(self, instance: object) -> object:
        # Read the foreign key column instead of the related row, so a list does not query once per row.
        if self.source_attrs:
            try:
                parent = get_attribute(instance, self.source_attrs[:-1])
                value = parent.serializable_value(self.source_attrs[-1])
            except AttributeError:
                pass
            else:
                # `serializable_value` returns the attribute itself when it is not a model field.
                return PKOnlyObject(pk=getattr(value, "pk", value))
        return super().get_attribute(instance)

    def to_representation(self, value: IntegrationRecord | PKOnlyObject | int) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, PKOnlyObject):
            return value.pk
        return value.id
