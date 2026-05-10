"""
Replay endpoint serializers shared by `HogFunctionViewSet` and `HogFlowViewSet`.

These define the request/response shape for `POST .../{kind}/{id}/replay`. The
view validates input, then proxies through to the Node CDP worker via
`replay_hog_invocations` in `posthog.plugins.plugin_server_api`. The worker
reads matching rows from ClickHouse `hog_invocation_results`, rehydrates from
the stored `invocation_globals`, and re-enqueues onto cyclotron.
"""

from rest_framework import serializers

# Hard cap on how many invocations can be queued for replay in a single request.
# The Node side enforces the same limit defensively — keep both in sync.
HOG_INVOCATION_REPLAY_MAX_COUNT = 1000


class HogInvocationReplayFilterSerializer(serializers.Serializer):
    """Filter shape used by the by-filter mode of the replay endpoint."""

    window_start = serializers.DateTimeField(required=True, help_text="Inclusive lower bound on `scheduled_at` (UTC).")
    window_end = serializers.DateTimeField(required=True, help_text="Exclusive upper bound on `scheduled_at` (UTC).")
    status = serializers.ListField(
        child=serializers.ChoiceField(choices=["running", "succeeded", "failed"]),
        required=False,
        help_text="Restrict to invocations whose latest status is one of these. Defaults to ['failed'].",
    )
    error_kind = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Restrict to invocations whose error_kind matches one of these (e.g. 'http_5xx', 'timeout').",
    )
    max_attempts = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=255,
        help_text="Skip invocations that have already been attempted this many times or more.",
    )
    max_count = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=HOG_INVOCATION_REPLAY_MAX_COUNT,
        help_text=(
            f"Maximum number of invocations to replay in this request. "
            f"Server-side cap is {HOG_INVOCATION_REPLAY_MAX_COUNT}."
        ),
    )


class HogInvocationReplayRequestSerializer(serializers.Serializer):
    """
    Replay invocations of a hog function or hog flow from their stored payloads.
    Provide EITHER `invocation_ids` (explicit list) OR `filter` (filter selection),
    not both.
    """

    invocation_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        max_length=HOG_INVOCATION_REPLAY_MAX_COUNT,
        help_text=(
            f"Explicit list of invocation IDs to replay. Capped at {HOG_INVOCATION_REPLAY_MAX_COUNT} per request."
        ),
    )
    filter = HogInvocationReplayFilterSerializer(
        required=False,
        help_text="Filter-based selection. Mutually exclusive with `invocation_ids`.",
    )

    def validate(self, attrs: dict) -> dict:
        has_ids = bool(attrs.get("invocation_ids"))
        has_filter = attrs.get("filter") is not None
        if has_ids == has_filter:
            raise serializers.ValidationError("Provide exactly one of 'invocation_ids' or 'filter'.")
        return attrs


class HogInvocationReplayResponseSerializer(serializers.Serializer):
    """Synchronous response from the replay endpoint — Node accepts the request and acks."""

    queued_count = serializers.IntegerField(help_text="Number of invocations the worker queued for replay.")
    skipped_count = serializers.IntegerField(
        help_text="Number of invocations the worker skipped (e.g. because they exceeded max_attempts)."
    )
