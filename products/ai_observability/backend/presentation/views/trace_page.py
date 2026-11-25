from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.throttling import BaseThrottle

from posthog.rate_limit import _UserBucketRateThrottle

from ...facade import api

PAGE_BOUNDS_BAD_REQUEST = OpenApiResponse(description="The trace IDs or the page bounds are invalid.")


# A conversation loads a page of up to 20 turns per request as it scrolls, so these rates clear fast scrolling by one
# person and stop a scripted loop of reads that each scan the events of a page of traces.
class ConversationReadBurstThrottle(_UserBucketRateThrottle):
    scope = "ai_conversation_read_burst"
    rate = "240/minute"


class ConversationReadSustainedThrottle(_UserBucketRateThrottle):
    scope = "ai_conversation_read_sustained"
    rate = "2400/hour"


class ConversationReadThrottled:
    """A view whose reads spend the caller's conversation budget: one per personal API key, or per user for browser
    sessions, which the default throttles leave unlimited."""

    def get_throttles(self) -> list[BaseThrottle]:
        return [*super().get_throttles(), ConversationReadBurstThrottle(), ConversationReadSustainedThrottle()]  # type: ignore[misc]


class TracePageRequestSerializer(serializers.Serializer):
    trace_ids = serializers.ListField(
        child=serializers.CharField(trim_whitespace=False),
        min_length=1,
        max_length=api.TRACE_LIST_MAX_LIMIT,
        help_text=f"The IDs of the traces on a page of the list, from 1 to {api.TRACE_LIST_MAX_LIMIT}. Items come back "
        "in this order, once per ID.",
    )


class TracePageWithBoundsRequestSerializer(TracePageRequestSerializer):
    earliest_created_at = serializers.DateTimeField(
        help_text="The earliest createdAt of the rows on the page. With latest_created_at, it bounds the read of "
        "traces older than the AI events retention.",
    )
    latest_created_at = serializers.DateTimeField(
        help_text="The latest createdAt of the rows on the page. It can't be before earliest_created_at.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        earliest, latest = attrs["earliest_created_at"], attrs["latest_created_at"]
        if latest < earliest:
            raise serializers.ValidationError("latest_created_at can't be before earliest_created_at.")
        if not api.is_usable_page_bounds(earliest, latest):
            raise serializers.ValidationError("The page bounds are out of range.")
        return attrs


class TraceTurnsRequestSerializer(TracePageWithBoundsRequestSerializer):
    trace_ids = serializers.ListField(
        child=serializers.CharField(trim_whitespace=False),
        min_length=1,
        max_length=api.TRACE_TURNS_MAX_IDS,
        help_text=f"The IDs of the traces to read the turns of, from 1 to {api.TRACE_TURNS_MAX_IDS}. Items come back "
        "in this order, at most once per ID. A trace with no generation and no trace event is left out.",
    )
    latest_created_at = serializers.DateTimeField(
        help_text="The latest createdAt of the traces. It can't be before earliest_created_at, nor more than "
        f"{api.TRACE_TURNS_MAX_SPAN.days} days after it.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if not api.is_readable_turns_span(attrs["earliest_created_at"], attrs["latest_created_at"]):
            raise serializers.ValidationError(
                f"The traces' createdAt values span more than {api.TRACE_TURNS_MAX_SPAN.days} days. Read them in "
                "smaller pages."
            )
        return attrs
