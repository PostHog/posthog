"""
Replay endpoint serializers shared by `HogFunctionViewSet` and `HogFlowViewSet`.

These define the request/response shape for `POST .../{kind}/{id}/replay`. The
view validates input, then proxies through to the Node CDP worker via
`replay_hog_invocations` in `posthog.plugins.plugin_server_api`. The worker
reads matching rows from ClickHouse `hog_invocation_results`, rehydrates from
the stored `invocation_globals`, and re-enqueues onto cyclotron.
"""

from datetime import timedelta

from rest_framework import serializers

# Hard cap on how many invocations can be queued for replay in a single request.
# The Node side enforces the same limit defensively — keep both in sync.
HOG_INVOCATION_REPLAY_MAX_COUNT = 1000

# Matches the ClickHouse TTL on `hog_invocation_results` (30 days). A replay
# window any longer would point at partitions that have already been dropped.
REPLAY_MAX_WINDOW_DAYS = 30


class HogInvocationReplayFilterSerializer(serializers.Serializer):
    """Filter shape for the replay endpoint. `window_start`/`window_end` are required."""

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
    invocation_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        max_length=HOG_INVOCATION_REPLAY_MAX_COUNT,
        help_text=(
            "Optional restriction to specific invocation IDs within the window. "
            f"Capped at {HOG_INVOCATION_REPLAY_MAX_COUNT} per request. Always combined with "
            "`window_start`/`window_end` so the ClickHouse query can be partition-pruned."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        start = attrs.get("window_start")
        end = attrs.get("window_end")
        if start and end:
            if end <= start:
                raise serializers.ValidationError("'window_end' must be after 'window_start'.")
            if end - start > timedelta(days=REPLAY_MAX_WINDOW_DAYS):
                raise serializers.ValidationError(
                    f"Replay window cannot exceed {REPLAY_MAX_WINDOW_DAYS} days "
                    f"(ClickHouse TTL on hog_invocation_results)."
                )
        return attrs


class HogInvocationReplayRequestSerializer(serializers.Serializer):
    """Replay invocations of a hog function or hog flow from their stored payloads."""

    filter = HogInvocationReplayFilterSerializer(
        required=True,
        help_text=(
            "Required. `window_start` / `window_end` pin the query to a small set of date "
            "partitions on the `hog_invocation_results` table. Optional `invocation_ids` "
            "restricts to specific invocations within that window."
        ),
    )


class HogInvocationReplayResponseSerializer(serializers.Serializer):
    """
    Response from the replay endpoint. The endpoint only enqueues a wrapper
    job onto the cyclotron `replay` queue — the actual ClickHouse paging and
    re-enqueue work happens asynchronously in the `cdp-replay-worker` service.
    Use `replay_job_id` to look up progress on the wrapper job later.
    """

    replay_job_id = serializers.CharField(
        help_text="ID of the cyclotron wrapper job that will run the replay. Use this to poll status."
    )
    queued_count = serializers.IntegerField(
        help_text="Always 0 — replay runs asynchronously. Kept for response shape stability.",
    )
    skipped_count = serializers.IntegerField(
        help_text="Always 0 — replay runs asynchronously. Kept for response shape stability.",
    )
