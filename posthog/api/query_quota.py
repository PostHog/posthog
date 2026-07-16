from rest_framework import serializers


class QueryQuotaLimitExtraSerializer(serializers.Serializer):
    billing_period_end = serializers.DateTimeField(
        help_text="ISO 8601 timestamp when query access resets for the current billing period."
    )


class QueryQuotaLimitResponseSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Stable error category. Always `quota_limited` for this response.")
    code = serializers.CharField(help_text="Stable error code. Always `quota_limit_exceeded` for this response.")
    detail = serializers.CharField(help_text="Customer-facing explanation of the query usage limit.")
    attr = serializers.CharField(
        allow_null=True, help_text="Always null because the error is not tied to an input field."
    )
    extra = QueryQuotaLimitExtraSerializer(
        required=False,
        help_text="Billing-period metadata. Omitted when the reset timestamp is unavailable.",
    )
