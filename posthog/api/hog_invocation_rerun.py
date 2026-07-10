"""
Rerun endpoint serializers shared by `HogFunctionViewSet` and `HogFlowViewSet`.

These define the request/response shape for `POST .../{kind}/{id}/rerun`. The
view validates input, then proxies through to the Node CDP worker via
`rerun_hog_invocations` in `posthog.plugins.plugin_server_api`. The worker
reads matching rows from ClickHouse `hog_invocation_results`, rehydrates from
the stored `invocation_globals`, and re-enqueues onto cyclotron.
"""

from datetime import timedelta

from rest_framework import serializers

from posthog.settings.utils import get_from_env

# Hard cap on how many invocations can be queued for rerun in a single request.
# Configurable via env so on-callers can bump it without a deploy if a batch
# rerun legitimately needs to drain more rows. The Node side reads the same
# env var from its CDP config — keep both in sync if you tweak the default.
HOG_INVOCATION_RERUN_MAX_COUNT = get_from_env("HOG_INVOCATION_RERUN_MAX_COUNT", default=10000, type_cast=int)

# Matches the ClickHouse TTL on `hog_invocation_results` (30 days). A rerun
# window any longer would point at partitions that have already been dropped.
RERUN_MAX_WINDOW_DAYS = 30


class HogInvocationRerunFilterSerializer(serializers.Serializer):
    """Filter shape for the rerun endpoint. `window_start`/`window_end` are required."""

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
        max_value=HOG_INVOCATION_RERUN_MAX_COUNT,
        help_text=(
            f"Maximum number of invocations to rerun in this request. "
            f"Server-side cap is {HOG_INVOCATION_RERUN_MAX_COUNT}."
        ),
    )
    invocation_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        max_length=HOG_INVOCATION_RERUN_MAX_COUNT,
        help_text=(
            "Optional restriction to specific invocation IDs within the window. "
            f"Capped at {HOG_INVOCATION_RERUN_MAX_COUNT} per request. Always combined with "
            "`window_start`/`window_end` so the ClickHouse query can be partition-pruned."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        start = attrs.get("window_start")
        end = attrs.get("window_end")
        if start and end:
            if end <= start:
                raise serializers.ValidationError("'window_end' must be after 'window_start'.")
            if end - start > timedelta(days=RERUN_MAX_WINDOW_DAYS):
                raise serializers.ValidationError(
                    f"Rerun window cannot exceed {RERUN_MAX_WINDOW_DAYS} days "
                    f"(ClickHouse TTL on hog_invocation_results)."
                )
        return attrs


class HogInvocationRerunRequestSerializer(serializers.Serializer):
    """Rerun invocations of a hog function or hog flow from their stored payloads."""

    filter = HogInvocationRerunFilterSerializer(
        required=True,
        help_text=(
            "Required. `window_start` / `window_end` pin the query to a small set of date "
            "partitions on the `hog_invocation_results` table. Optional `invocation_ids` "
            "restricts to specific invocations within that window."
        ),
    )


class HogInvocationRerunResponseSerializer(serializers.Serializer):
    """
    Response from the rerun endpoint. The endpoint only enqueues a wrapper
    job onto the cyclotron `rerun` queue — the actual ClickHouse paging and
    re-enqueue work happens asynchronously in the `cdp-rerun-worker` service.
    Use `rerun_job_id` to look up progress on the wrapper job later.
    """

    rerun_job_id = serializers.CharField(
        help_text="ID of the cyclotron wrapper job that will run the rerun. Use this to poll status."
    )
    queued_count = serializers.IntegerField(
        help_text="Always 0 — rerun runs asynchronously. Kept for response shape stability.",
    )
    skipped_count = serializers.IntegerField(
        help_text="Always 0 — rerun runs asynchronously. Kept for response shape stability.",
    )
