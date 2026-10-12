import typing

import pydantic
import posthoganalytics
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from posthog.schema import HogQLQueryModifiers

from posthog.models import Team

HOGQL_MODIFIERS_HELP_TEXT = (
    "HogQL modifiers to use when the query runs, as an object keyed by modifier name, for example "
    "{\"convertToProjectTimezone\": true}. Only supported when 'model' is 'hogql'. Each modifier set here "
    "overrides the project modifier with the same name, and the project modifiers apply to all others. If neither "
    "sets convertToProjectTimezone, it defaults to false, so timestamps are exported in UTC. Set it to true to "
    "export timestamps in the project timezone instead. Unknown modifier names are rejected. On update, the object "
    "replaces the modifiers stored on the export, so include every modifier to keep, or send null to remove them all."
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


def check_high_frequency_batch_exports_enabled(team: Team) -> None:
    """Raise if high-frequency batch exports are not enabled for the team."""
    if not posthoganalytics.feature_enabled(
        "high-frequency-batch-exports",
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
        raise PermissionDenied("Higher frequency batch exports are not enabled for this team.")


@extend_schema_field(HogQLQueryModifiers)  # type: ignore[arg-type]
class HogQLModifiersField(serializers.JSONField):
    """HogQL modifiers, validated against `HogQLQueryModifiers` and stored as a plain dict."""

    loaded: HogQLQueryModifiers | None = None

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
        else:
            self.loaded = modifiers
        return modifiers.model_dump(mode="json", exclude_none=True)
