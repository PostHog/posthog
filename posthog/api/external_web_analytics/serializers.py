from rest_framework import serializers


EXTERNAL_WEB_ANALYTICS_PAGINATION_DEFAULT_LIMIT = 100
EXTERNAL_WEB_ANALYTICS_PAGINATION_MAX_LIMIT = 1000

EXTERNAL_WEB_ANALYTICS_SUPPORTED_METRICS = ["visitors", "views", "sessions", "bounce_rate", "session_duration"]


class WebAnalyticsRequestSerializer(serializers.Serializer):
    date_from = serializers.DateField(help_text="Start date for the query")
    date_to = serializers.DateField(help_text="End date for the query")
    domain = serializers.CharField(help_text="Domain to filter by")

    filter_test_accounts = serializers.BooleanField(default=True, help_text="Filter out test accounts", required=False)
    do_path_cleaning = serializers.BooleanField(default=True, help_text="Apply URL path cleaning", required=False)


class WebAnalyticsOverviewRequestSerializer(WebAnalyticsRequestSerializer):
    pass


class WebAnalyticsTrendRequestSerializer(WebAnalyticsRequestSerializer):
    metric = serializers.ChoiceField(
        choices=EXTERNAL_WEB_ANALYTICS_SUPPORTED_METRICS, help_text="The metric to show over time"
    )
    interval = serializers.ChoiceField(
        choices=["day", "week", "month"], default="day", help_text="Time interval for data aggregation", required=False
    )
    limit = serializers.IntegerField(
        default=100, min_value=1, max_value=1000, help_text="Number of data points to return", required=False
    )
    offset = serializers.IntegerField(default=0, min_value=0, help_text="Number of data points to skip", required=False)


class WebAnalyticsBreakdownRequestSerializer(WebAnalyticsRequestSerializer):
    breakdown_by = serializers.ChoiceField(
        choices=[
            # Page-related
            "page",
            "initial_page",
            "exit_page",
            "exit_click",
            "screen_name",
            # Traffic sources
            "initial_channel_type",
            "initial_referring_domain",
            "initial_utm_source",
            "initial_utm_campaign",
            "initial_utm_medium",
            "initial_utm_term",
            "initial_utm_content",
            "initial_utm_source_medium_campaign",
            # Device & technical
            "browser",
            "os",
            "viewport",
            "device_type",
            # Geographic
            "country",
            "region",
            "city",
            "timezone",
            "language",
        ],
        help_text="Property to break down by",
    )

    metrics = serializers.CharField(
        default=",".join(EXTERNAL_WEB_ANALYTICS_SUPPORTED_METRICS),
        help_text="Comma-separated list of metrics to include",
        required=False,
    )

    limit = serializers.IntegerField(
        default=EXTERNAL_WEB_ANALYTICS_PAGINATION_DEFAULT_LIMIT,
        min_value=1,
        max_value=EXTERNAL_WEB_ANALYTICS_PAGINATION_MAX_LIMIT,
        help_text="Number of results to return",
        required=False,
    )

    offset = serializers.IntegerField(default=0, min_value=0, help_text="Number of results to skip", required=False)

    def validate_metrics(self, value):
        valid_choices = EXTERNAL_WEB_ANALYTICS_SUPPORTED_METRICS

        if isinstance(value, str):
            metrics = [m.strip() for m in value.split(",")]
        else:
            metrics = value

        for metric in metrics:
            if metric not in valid_choices:
                raise serializers.ValidationError(
                    f"Invalid metric: {metric}. Valid choices: {', '.join(valid_choices)}"
                )

        return metrics


# Response serializers
class WebAnalyticsOverviewResponseSerializer(serializers.Serializer):
    visitors = serializers.IntegerField(help_text="Unique visitors")
    views = serializers.IntegerField(help_text="Total page views")
    sessions = serializers.IntegerField(help_text="Total sessions")
    bounce_rate = serializers.FloatField(help_text="Bounce rate", min_value=0, max_value=1)
    session_duration = serializers.FloatField(help_text="Average session duration in seconds")


class WebAnalyticsTrendPointSerializer(serializers.Serializer):
    time = serializers.DateTimeField(help_text="Datetime for this data point")
    value = serializers.IntegerField(help_text="The metric value for this date")


class WebAnalyticsListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Total number of items available")
    next = serializers.URLField(required=False, allow_null=True, help_text="URL for next page of results")
    previous = serializers.URLField(required=False, allow_null=True, help_text="URL for previous page of results")
    results = serializers.ListField(help_text="Array of items")


class WebAnalyticsTrendResponseSerializer(WebAnalyticsListResponseSerializer):
    results = WebAnalyticsTrendPointSerializer(many=True, help_text="Array of data points for the metric")


class WebAnalyticsBreakdownResponseSerializer(WebAnalyticsListResponseSerializer):
    results = serializers.ListField(help_text="Array of breakdown items")
