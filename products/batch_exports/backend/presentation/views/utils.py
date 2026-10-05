import typing

import pydantic
import posthoganalytics
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from posthog.schema import HogQLQueryModifiers

from posthog.models import Team

HOGQL_MODIFIERS_HELP_TEXT = (
    "HogQL modifiers to use when the query runs. Only supported when 'model' is 'hogql'. "
    "Each modifier set here overrides the project modifier with the same name, and the project "
    "modifiers apply to all others. For example, set convertToProjectTimezone to false to export "
    "timestamps in UTC instead of the project timezone."
)


def check_hogql_batch_exports_enabled(team: Team) -> None:
    """Raise if HogQL-powered batch exports are not enabled for the team."""
    if not posthoganalytics.feature_enabled(
        "hogql-batch-exports",
        str(team.uuid),
        groups={"organization": str(team.organization.id)},
        group_properties={
            "organization": {
                "id": str(team.organization.id),
                "created_at": team.organization.created_at,
            }
        },
        send_feature_flag_events=False,
    ):
        raise PermissionDenied("HogQL batch exports are not enabled for this team.")


@extend_schema_field(HogQLQueryModifiers)  # type: ignore[arg-type]
class HogQLModifiersField(serializers.JSONField):
    """HogQL modifiers, validated against `HogQLQueryModifiers` and stored as a plain dict."""

    def to_internal_value(self, data: typing.Any) -> dict[str, typing.Any]:
        value = super().to_internal_value(data)
        try:
            modifiers = HogQLQueryModifiers.model_validate(value)
        except pydantic.ValidationError as e:
            messages = []
            for error in e.errors():
                location = ".".join(str(part) for part in error["loc"])
                messages.append(f"{location}: {error['msg']}" if location else error["msg"])
            raise serializers.ValidationError(messages) from e
        return modifiers.model_dump(mode="json", exclude_none=True)
