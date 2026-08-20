"""
Cancel endpoint serializers for `HogFlowViewSet`.

These define the request/response shape for `POST .../hog_flows/{id}/invocations/cancel`.
The view validates input, then proxies through to the Node CDP worker via
`cancel_hog_flow_invocations` in `posthog.plugins.plugin_server_api`. The worker side only
flags cyclotron jobs and wakes parked ones; the workflow workers terminate flagged runs with
their lifecycle rows, metrics, and logs.
"""

from rest_framework import serializers

from posthog.api.hog_invocation_rerun import HOG_INVOCATION_RERUN_MAX_COUNT


class HogInvocationCancelRequestSerializer(serializers.Serializer):
    """Cancel in-flight invocations of a workflow. Provide exactly one selector."""

    invocation_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        min_length=1,
        max_length=HOG_INVOCATION_RERUN_MAX_COUNT,
        help_text=(
            "Cancel these specific invocations. "
            f"Capped at {HOG_INVOCATION_RERUN_MAX_COUNT} per request. Invocations that already "
            "finished are skipped rather than failing the request."
        ),
    )
    all = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Cancel every in-flight invocation of this workflow, including parked delays and waits.",
    )

    def validate(self, attrs: dict) -> dict:
        has_ids = attrs.get("invocation_ids") is not None
        has_all = attrs.get("all") is True
        if has_ids == has_all:
            raise serializers.ValidationError("Provide exactly one of 'invocation_ids' or 'all'.")
        return attrs


class HogInvocationCancelResponseSerializer(serializers.Serializer):
    """
    Response from the cancel endpoint. Cancellation is asynchronous: this call flags runs, and
    the workflow workers terminate them shortly after (immediately for parked runs, at the next
    step boundary for runs mid-execution). A run stays 'running' in listings until that happens.
    """

    marked = serializers.IntegerField(help_text="In-flight runs newly flagged for cancellation by this request.")
    remaining = serializers.IntegerField(
        help_text="Matching in-flight runs not yet flagged. Non-zero on very large workflows; call again."
    )
    done = serializers.BooleanField(help_text="True when no matching in-flight runs remain unflagged.")
