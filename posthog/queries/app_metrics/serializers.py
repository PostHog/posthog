from rest_framework import serializers


class AppMetricsRequestSerializer(serializers.Serializer):
    category = serializers.ChoiceField(
        # Keep in sync with plugin-server/src/worker/ingestion/app-metrics.ts
        choices=["processEvent", "onEvent", "exportEvents", "scheduledTask", "webhook", "composeWebhook"],
        help_text="What to gather metrics for",
        required=False,
    )
    date_from = serializers.CharField(
        default="-30d",
        help_text="What date to filter the results from. Can either be a date `2021-01-01`, or a relative date, like `-7d` for last seven days, `-1m` for last month, `mStart` for start of the month or `yStart` for the start of the year.",
    )
    date_to = serializers.CharField(
        required=False,
        help_text="What date to filter the results to. Can either be a date `2021-01-01`, or a relative date, like `-7d` for last seven days, `-1m` for last month, `mStart` for start of the month or `yStart` for the start of the year.",
    )
    job_id = serializers.CharField(help_text="Set this to filter results to a particular job", required=False)


class AppMetricsErrorsRequestSerializer(serializers.Serializer):
    category = serializers.ChoiceField(
        # Keep in sync with plugin-server/src/worker/ingestion/app-metrics.ts
        choices=["processEvent", "onEvent", "exportEvents", "scheduledTask", "webhook", "composeWebhook"],
        help_text="What to gather errors for",
        required=False,
    )
    error_type = serializers.CharField(required=True, help_text="What error type to filter for.")
    job_id = serializers.CharField(help_text="Set this to filter results to a particular job", required=False)
