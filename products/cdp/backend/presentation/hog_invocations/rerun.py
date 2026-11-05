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

# The worker sends the whole ID list as one ClickHouse query parameter on every page, and a longer list
# fails every page: `http_max_field_value_size` (128 KiB) fits at most 2912 URL-encoded UUIDs.
HOG_INVOCATION_RERUN_MAX_IDS = min(2500, HOG_INVOCATION_RERUN_MAX_COUNT)

# Not `UUIDField`: stored IDs are version 0 UUIDs, and the generated `zod.uuid()` schema rejects that version.
INVOCATION_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# Matches the ClickHouse TTL on `hog_invocation_results` (30 days). A rerun
# window any longer would point at partitions that have already been dropped.
RERUN_MAX_WINDOW_DAYS = 30


class HogInvocationRerunFilterSerializer(serializers.Serializer):
    """Filter shape for the rerun endpoint. `window_start`/`window_end` are required."""

    window_start = serializers.DateTimeField(required=True, help_text="Inclusive lower bound on `scheduled_at` (UTC).")
    window_end = serializers.DateTimeField(required=True, help_text="Exclusive upper bound on `scheduled_at` (UTC).")
    status = serializers.ListField(
        child=serializers.ChoiceField(choices=["running", "succeeded", "failed", "canceled"]),
        required=False,
        help_text="Restrict to invocations whose latest status is one of these. Defaults to ['failed'].",
    )
    error_kind = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Restrict to invocations whose error_kind matches one of these (e.g. 'http_5xx', 'timeout').",
    )
    error_message_contains = serializers.CharField(
        required=False,
        max_length=200,
        help_text=(
            "Restrict to invocations whose error_message contains this substring (case-insensitive). "
            "Use to isolate one failure mode when error_kind is too coarse (most app-level errors "
            "share the 'hog_error' kind)."
        ),
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
        child=serializers.RegexField(INVOCATION_ID_PATTERN, error_messages={"invalid": "Must be a lowercase UUID."}),
        required=False,
        min_length=1,
        max_length=HOG_INVOCATION_RERUN_MAX_IDS,
        error_messages={
            "min_length": "Provide at least one invocation ID, or leave the list out to match the whole window.",
            "max_length": "You can rerun up to {max_length} invocations by ID in one request. "
            "Split the list into smaller requests.",
        },
        help_text=(
            "Optional restriction to specific invocation IDs within the window. Omit it to match the whole "
            f"window. Capped at {HOG_INVOCATION_RERUN_MAX_IDS} per request. Always combined with "
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
