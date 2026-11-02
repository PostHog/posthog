from datetime import timedelta

from django.utils import timezone

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from posthog.api.fields import JSONTolerantListField, RepeatedOrCommaSeparatedListField

from products.annotations.backend.facade.change_feed import ChangeKind

DEFAULT_WINDOW = timedelta(hours=24)
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class ChangeKindsField(RepeatedOrCommaSeparatedListField, JSONTolerantListField):
    """Repeated keys, one comma-joined value (the generated frontend client) or one JSON array (the MCP client).

    The base order matters: JSONTolerantListField reads a JSON array before
    RepeatedOrCommaSeparatedListField splits on commas.
    """


class ChangeFeedQuerySerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(
        required=False,
        help_text="Start of the time window (inclusive), ISO 8601. Defaults to 24 hours before `date_to`.",
    )
    date_to = serializers.DateTimeField(
        required=False,
        help_text="End of the time window (inclusive), ISO 8601. Defaults to now.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=DEFAULT_LIMIT,
        min_value=1,
        max_value=MAX_LIMIT,
        help_text=f"Maximum number of changes to return, newest first. Defaults to {DEFAULT_LIMIT}, at most {MAX_LIMIT}.",
    )
    kinds = ChangeKindsField(
        child=serializers.ChoiceField(choices=ChangeKind.choices),
        required=False,
        default=[],
        help_text=(
            "Return only these kinds of change. Omit to return every kind. "
            "Use `feature_flag` and `experiment` to see configuration edits without releases and annotations."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        date_to = attrs.get("date_to") or timezone.now()
        date_from = attrs.get("date_from") or date_to - DEFAULT_WINDOW
        if date_from > date_to:
            raise serializers.ValidationError("date_from must be before date_to.")
        return {**attrs, "date_from": date_from, "date_to": date_to}


class ChangeFeedItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ChangeKind.choices, help_text="The source of the change.")
    timestamp = serializers.DateTimeField(
        help_text="When the change happened. For annotations, this is the time the annotation marks."
    )
    item_id = serializers.CharField(
        help_text="ID of the changed object: the feature flag, experiment, release, or annotation ID."
    )
    name = serializers.CharField(
        allow_null=True,
        help_text="Display name: the flag key, experiment name, release version, or annotation text.",
    )
    activity = serializers.CharField(
        help_text="What happened, for example `created`, `updated`, `deleted`, `released`, or `annotated`."
    )
    changed_fields = serializers.ListField(
        child=serializers.CharField(),
        help_text="For flag and experiment updates, the names of the fields that changed. Empty for other kinds.",
    )
    service = serializers.CharField(
        allow_null=True, help_text="For releases, the project or service the release belongs to. Null for other kinds."
    )
    actor_name = serializers.CharField(
        allow_null=True, help_text="Name or email of the person who made the change. Null for automated changes."
    )


# The `list` action returns one feed object, not an array of feeds.
@extend_schema_serializer(many=False)
class ChangeFeedSerializer(serializers.Serializer):
    results = ChangeFeedItemSerializer(many=True, help_text="Changes in the time window, newest first.")
    has_more = serializers.BooleanField(
        help_text="True when the window holds more changes than `limit`. Narrow the window to see the rest."
    )
