from collections.abc import Mapping
from typing import Any

from django.db.models import TextChoices

from rest_framework import serializers

from posthog.caching.insight_result import InsightResult
from posthog.renderers import SafeJSONRenderer

from products.dashboards.backend.facade.api import has_frames, insight_frames


class FramesRenderer(SafeJSONRenderer):
    """JSON, selected by `?format=frames`. DRF reads `format` as the renderer to use, so the name must exist."""

    format = "frames"


class CachedTileFormat(TextChoices):
    FRAMES = "frames", "Frames"
    RESULT = "result", "Result"


class FrameFieldType(TextChoices):
    TIME = "time", "Time"
    NUMBER = "number", "Number"


class FrameFieldSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Field name: 'time' for the time field, 'value' for a number field.")
    type = serializers.ChoiceField(choices=FrameFieldType.choices, help_text="What the values are.")
    values = serializers.ListField(
        child=serializers.FloatField(allow_null=True),
        help_text="A time field holds epoch milliseconds. A number field holds null for a gap.",
    )
    unit = serializers.CharField(allow_null=True, help_text="UCUM unit of the values, e.g. 'By' or 'ms'.")


class FrameMetaSerializer(serializers.Serializer):
    interval = serializers.CharField(
        allow_null=True, help_text="Bucket size as a PostHog interval name, e.g. 'minute_5', 'hour' or 'day'."
    )
    date_from = serializers.DateTimeField(allow_null=True, help_text="Start of the range the frame covers.")
    date_to = serializers.DateTimeField(allow_null=True, help_text="End of the range the frame covers.")
    previous = serializers.BooleanField(
        help_text="Whether the frame is the compared period. Its dates are that period's dates."
    )


class FrameSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Series name, as the chart legend shows it.")
    labels = serializers.DictField(
        child=serializers.CharField(), help_text="Label values that identify the series within the tile."
    )
    meta = FrameMetaSerializer(help_text="Interval and date range of the frame.")

    def get_fields(self) -> dict[str, serializers.Field]:
        # `fields` is a Serializer attribute, so the declared field is added here instead.
        fields = super().get_fields()
        fields["fields"] = FrameFieldSerializer(many=True, help_text="A time field, then one number field.")
        return fields


def requires_parsed_result(query: Any) -> bool:
    """Whether a tile's frames are built from its parsed result. Other tiles keep the raw cached bytes."""
    return isinstance(query, Mapping) and has_frames(query)


def cached_tile_format(insight_data: dict[str, Any], query: Any, result: InsightResult) -> dict[str, Any]:
    """The `format` and `frames` of a cached tile hit. A tile with frames nulls its result, which the frames replace."""
    frames = insight_frames(query, result) if isinstance(query, Mapping) else None
    if frames is None:
        return {"format": CachedTileFormat.RESULT}
    # Null rather than absent: the published schema requires `result`.
    insight_data["result"] = None
    return {"format": CachedTileFormat.FRAMES, "frames": frames}
