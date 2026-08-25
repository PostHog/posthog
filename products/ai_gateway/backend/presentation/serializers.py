from decimal import Decimal

from rest_framework import serializers

# A window shorter than an hour would reset faster than settlement lands, so a
# limit set there could never bind. The ceiling matches the gateway's.
MIN_WINDOW_SECONDS = 3600
MAX_WINDOW_SECONDS = 366 * 24 * 60 * 60
MIN_LIMIT_USD = Decimal("0.01")
MAX_LIMIT_USD = Decimal("1000000000")

# Read and write share these so a limit round-trips through the API unchanged.
_LIMIT_MAX_DIGITS = 19
_LIMIT_DECIMAL_PLACES = 6
_WINDOW_HELP_TEXT = (
    "Length of the accounting window the limit applies to, in seconds. The window is fixed rather than sliding: it "
    "starts at the first spend after a reset and the counter resets once per window."
)


class SpendLimitSerializer(serializers.Serializer):
    limit_usd = serializers.DecimalField(
        max_digits=_LIMIT_MAX_DIGITS,
        decimal_places=_LIMIT_DECIMAL_PLACES,
        allow_null=True,
        help_text="The limit in USD as a decimal string, or null when no limit is set.",
    )
    window_seconds = serializers.IntegerField(
        allow_null=True,
        help_text=f"{_WINDOW_HELP_TEXT} Null when no limit is set.",
    )
    available = serializers.BooleanField(
        help_text=(
            "Whether spend limits are available on this PostHog deployment. False means no limit can be set here, "
            "so any limit shown in the app informs only."
        ),
    )


class SpendLimitWriteSerializer(serializers.Serializer):
    limit_usd = serializers.DecimalField(
        max_digits=_LIMIT_MAX_DIGITS,
        decimal_places=_LIMIT_DECIMAL_PLACES,
        min_value=MIN_LIMIT_USD,
        max_value=MAX_LIMIT_USD,
        help_text=(
            "The limit in USD. The gateway stores the limit and, once enforcement is live for this traffic, "
            "refuses spend past it until the window resets."
        ),
    )
    window_seconds = serializers.IntegerField(
        min_value=MIN_WINDOW_SECONDS,
        max_value=MAX_WINDOW_SECONDS,
        help_text=f"{_WINDOW_HELP_TEXT} At least an hour and at most 366 days.",
    )


class SpendLimitErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="What went wrong, in a form that can be shown to a person.")
