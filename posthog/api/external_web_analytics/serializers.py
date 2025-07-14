from rest_framework import serializers


class WebAnalyticsRequestOptionsSerializer(serializers.Serializer):
    filter_test_accounts = serializers.BooleanField(default=True, help_text="Filter out test accounts")
    do_path_cleaning = serializers.BooleanField(default=True, help_text="Apply URL path cleaning")


class WebAnalyticsRequestSerializer(serializers.Serializer):
    date_from = serializers.DateField(help_text="Start date for the query")
    date_to = serializers.DateField(help_text="End date for the query")

    filters = serializers.JSONField(
        required=False,
        help_text="Array of property filters: [{type: 'event|person|session', key: string, operator: string, value: any}]",
    )

    domain = serializers.CharField(help_text="Domain to filter by")

    options = WebAnalyticsRequestOptionsSerializer(required=False, default=WebAnalyticsRequestOptionsSerializer())


class WebAnalyticsOverviewRequestSerializer(WebAnalyticsRequestSerializer):
    pass


class WebAnalyticsTrendRequestSerializer(WebAnalyticsRequestSerializer):
    metric = serializers.ChoiceField(
        choices=["visitors", "views", "sessions"], help_text="The metric to show over time"
    )
    interval = serializers.ChoiceField(
        choices=["minute", "hour", "day", "week", "month"],
        default="day",
        help_text="Time interval for data aggregation",
    )


class WebAnalyticsBreakdownRequestSerializer(WebAnalyticsRequestSerializer):
    """Request parameters for breakdown endpoint"""

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
            # Additional
            "frustration_metrics",
        ],
        help_text="Property to break down by",
    )
    metrics = serializers.MultipleChoiceField(
        choices=[
            "visitors",
            "views",
            "clicks",
            "bounce_rate",
            "session_duration",
        ],
        required=False,
        help_text="Metrics to include for each breakdown value",
        default={"visitors", "views", "bounce_rate"},
    )
    limit = serializers.IntegerField(default=25, min_value=1, max_value=100, help_text="Number of results to return")


# Response serializers
class WebAnalyticsOverviewResponseSerializer(serializers.Serializer):
    visitors = serializers.IntegerField(help_text="Unique visitors")
    views = serializers.IntegerField(help_text="Total page views")
    sessions = serializers.IntegerField(help_text="Total sessions")
    bounce_rate = serializers.FloatField(help_text="Bounce rate (0-1)")
    session_duration = serializers.FloatField(help_text="Average session duration in seconds")


class WebAnalyticsTrendPointSerializer(serializers.Serializer):
    datetime = serializers.DateTimeField(help_text="Datetime for this data point")
    value = serializers.IntegerField(help_text="The metric value for this date")


class WebAnalyticsTrendResponseSerializer(serializers.Serializer):
    metric = serializers.CharField(help_text="The metric being measured")
    interval = serializers.CharField(help_text="Time interval used")
    series = WebAnalyticsTrendPointSerializer(many=True, help_text="Time series data")


class WebAnalyticsBreakdownResponseSerializer(serializers.Serializer):
    breakdown_by = serializers.CharField(help_text="Property used for breakdown")
    results = serializers.ListField(help_text="Breakdown results with flexible metrics")
    has_more = serializers.BooleanField(help_text="Whether there are more results available")
    total_count = serializers.IntegerField(help_text="Total number of items available", required=False)
