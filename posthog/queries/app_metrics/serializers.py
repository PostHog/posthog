from rest_framework import serializers


class AppMetricsRequestSerializer(serializers.Serializer):
    category = serializers.ChoiceField(
        # Keep in sync with plugin-server/src/worker/ingestion/app-metrics.ts
        choices=["processEvent", "onEvent", "exportEvents"],
        help_text="What date to filter the results from",
        required=True,
    )
    date_from = serializers.ChoiceField(
        choices=["-7d", "-30d"], help_text="What date to filter the results from", default="-30d"
    )
    date_to = serializers.CharField(
        required=False,
        help_text="What date to filter the results to",
    )
    job_id = serializers.CharField(help_text="Set this to filter results to a particular job", required=False)
