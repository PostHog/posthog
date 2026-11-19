"""DRF serializers for apm."""

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from products.apm.backend.facade.api import DependencyKind, HealthStatus, TimeSpentComponentKind, UsageSignal


class WindowRequestSerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(
        required=False, help_text="Start of the window, ISO 8601. Defaults to one hour before date_to."
    )
    date_to = serializers.DateTimeField(required=False, help_text="End of the window, ISO 8601. Defaults to now.")


class ServicesHealthRequestSerializer(WindowRequestSerializer):
    environment = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text=(
            "Environment to list, as resolved from span resource attributes. Omit it for every environment. "
            "Pass an empty value for spans that set no environment."
        ),
    )


class EndpointsHealthRequestSerializer(ServicesHealthRequestSerializer):
    service = serializers.CharField(
        required=False, allow_blank=False, max_length=400, help_text="Only list the endpoints of this service."
    )


class HealthRowSerializer(serializers.Serializer):
    request_rate = serializers.FloatField(allow_null=True, help_text="Requests per second over the window.")
    error_rate = serializers.FloatField(allow_null=True, help_text="Share of requests with an error status, 0 to 1.")
    p95_ms = serializers.FloatField(allow_null=True, help_text="95th percentile request duration in milliseconds.")
    span_count = serializers.IntegerField(help_text="Requests counted in the window.")
    error_count = serializers.IntegerField(help_text="Requests with an error status in the window.")


class ServiceHealthSerializer(serializers.Serializer):
    service_name = serializers.CharField(help_text="The service.name resource attribute.")
    environment = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        help_text="The environment filter the row was computed for: null for every environment, empty for spans with no environment.",
    )
    status = serializers.ChoiceField(choices=HealthStatus.choices, help_text="Health band from the error rate.")
    health = HealthRowSerializer(help_text="The health row every surface renders.")
    sparkline = serializers.ListField(
        child=serializers.IntegerField(), help_text="Request counts per bucket across the window, oldest first."
    )


@extend_schema_serializer(many=False)  # drf-spectacular wraps a `list` action's response in an array by default
class ServicesHealthResponseSerializer(serializers.Serializer):
    results = ServiceHealthSerializer(many=True, help_text="One row per service, worst status first.")
    environments = serializers.ListField(
        child=serializers.CharField(allow_null=True),
        help_text="Environments seen in the window. Null stands for spans that set no environment.",
    )
    environment = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        help_text="The environment filter the rows were computed for: null for every environment, empty for spans with no environment.",
    )
    date_from = serializers.DateTimeField(help_text="Start of the window used.")
    date_to = serializers.DateTimeField(help_text="End of the window used.")


class EndpointHealthSerializer(serializers.Serializer):
    service_name = serializers.CharField(help_text="The service.name resource attribute.")
    endpoint = serializers.CharField(
        help_text='The endpoint label: the entry span name, or "<METHOD> <route>" when the span name is only an HTTP method and the span carries a route.'
    )
    span_name = serializers.CharField(help_text="The raw entry span name the row counts, for tracing filters.")
    route_attribute = serializers.CharField(
        allow_null=True,
        help_text="The span attribute the route came from (http.route or url.template), or null when the label is the span name.",
    )
    route = serializers.CharField(allow_null=True, help_text="The route appended to the span name, or null.")
    environment = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        help_text="The environment filter the row was computed for: null for every environment, empty for spans with no environment.",
    )
    status = serializers.ChoiceField(choices=HealthStatus.choices, help_text="Health band from the error rate.")
    health = HealthRowSerializer(help_text="The health row every surface renders.")


@extend_schema_serializer(many=False)
class EndpointsHealthResponseSerializer(serializers.Serializer):
    results = EndpointHealthSerializer(many=True, help_text="One row per service and endpoint, worst status first.")
    environment = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        help_text="The environment filter the rows were computed for: null for every environment, empty for spans with no environment.",
    )
    service = serializers.CharField(allow_null=True, help_text="The service filter applied, if any.")
    date_from = serializers.DateTimeField(help_text="Start of the window used.")
    date_to = serializers.DateTimeField(help_text="End of the window used.")


class ServiceEdgeSerializer(serializers.Serializer):
    caller = serializers.CharField(help_text="The calling service.")
    callee = serializers.CharField(help_text="The called service.")
    calls = serializers.IntegerField(help_text="Calls from the caller into the callee in the sampled traces.")
    error_count = serializers.IntegerField(help_text="Calls with an error status on the callee span.")
    p95_ms = serializers.FloatField(allow_null=True, help_text="95th percentile duration of the callee span, in ms.")


@extend_schema_serializer(many=False)
class ServiceMapResponseSerializer(serializers.Serializer):
    edges = ServiceEdgeSerializer(many=True, help_text="One edge per calling and called service, most calls first.")
    trace_count = serializers.IntegerField(help_text="Traces sampled to build the map.")
    environment = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        help_text="The environment filter the map was built for: null for every environment, empty for spans with no environment.",
    )
    date_from = serializers.DateTimeField(help_text="Start of the window used.")
    date_to = serializers.DateTimeField(help_text="End of the window used.")


class DependenciesRequestSerializer(ServicesHealthRequestSerializer):
    service = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=400,
        help_text="Only edges where this service is the caller or the callee.",
    )


class DependencyEdgeSerializer(serializers.Serializer):
    caller = serializers.CharField(help_text="The calling service.")
    callee = serializers.CharField(
        help_text="The called service, or for an inferred dependency the peer service, database, queue or host it names."
    )
    inferred = serializers.BooleanField(
        help_text="True when the callee sends no spans and is named by the caller's client span attributes."
    )
    kind = serializers.ChoiceField(choices=DependencyKind.choices, help_text="What the callee is.")
    requests = serializers.IntegerField(help_text="Calls from the caller into the callee in the window.")
    error_count = serializers.IntegerField(
        help_text="Calls with an error status, on the caller's client span when it has one."
    )
    p95_ms = serializers.FloatField(
        allow_null=True, help_text="95th percentile call duration in ms, on the caller's client span when it has one."
    )


@extend_schema_serializer(many=False)
class DependenciesResponseSerializer(serializers.Serializer):
    edges = DependencyEdgeSerializer(many=True, help_text="One edge per caller and callee, most requests first.")
    truncated = serializers.BooleanField(help_text="True when more edges matched than the response holds.")
    environment = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        help_text="The environment filter the edges were computed for: null for every environment, empty for spans with no environment.",
    )
    service = serializers.CharField(allow_null=True, help_text="The service filter applied, if any.")
    date_from = serializers.DateTimeField(help_text="Start of the window used.")
    date_to = serializers.DateTimeField(help_text="End of the window used.")


class DeploymentsRequestSerializer(ServicesHealthRequestSerializer):
    service = serializers.CharField(required=True, max_length=400, help_text="The service to list versions for.")


class DeploymentVersionSerializer(serializers.Serializer):
    version = serializers.CharField(help_text="The service.version resource attribute.")
    first_seen = serializers.DateTimeField(help_text="First span of this version in the window.")
    last_seen = serializers.DateTimeField(help_text="Last span of this version in the window.")
    requests = serializers.IntegerField(help_text="Requests counted in the window.")
    error_count = serializers.IntegerField(help_text="Requests with an error status.")
    error_rate = serializers.FloatField(allow_null=True, help_text="Share of requests with an error status, 0 to 1.")
    p95_ms = serializers.FloatField(allow_null=True, help_text="95th percentile request duration in milliseconds.")
    previous_version = serializers.CharField(
        allow_null=True, help_text="The version first seen just before this one. Null for the oldest."
    )
    error_rate_change = serializers.FloatField(
        allow_null=True, help_text="Error rate minus the previous version's, as a fraction."
    )
    p95_change_pct = serializers.FloatField(
        allow_null=True, help_text="Change in p95 from the previous version, in percent."
    )
    active = serializers.BooleanField(help_text="True for the version first seen most recently.")


@extend_schema_serializer(many=False)
class DeploymentsResponseSerializer(serializers.Serializer):
    results = DeploymentVersionSerializer(many=True, help_text="One row per version, oldest first.")
    service = serializers.CharField(help_text="The service the versions belong to.")
    environment = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        help_text="The environment filter the rows were computed for: null for every environment, empty for spans with no environment.",
    )
    date_from = serializers.DateTimeField(help_text="Start of the window used.")
    date_to = serializers.DateTimeField(help_text="End of the window used.")


class EndpointTimeSpentRequestSerializer(ServicesHealthRequestSerializer):
    service = serializers.CharField(
        allow_blank=False, max_length=400, help_text="The service that handles the endpoint."
    )
    endpoint = serializers.CharField(
        allow_blank=False, max_length=2000, help_text="The endpoint label, as listed by apm/endpoints."
    )


class TimeSpentComponentSerializer(serializers.Serializer):
    name = serializers.CharField(
        help_text="The service name, the inferred dependency (for example a database system or host), or 'Other'."
    )
    kind = serializers.ChoiceField(
        choices=TimeSpentComponentKind.choices,
        help_text="service: an instrumented service. inferred: a dependency seen only through client spans. other: the remaining components combined.",
    )
    total_ms = serializers.FloatField(help_text="Self-time summed across the sampled requests, in milliseconds.")
    avg_ms_per_request = serializers.FloatField(help_text="Self-time per sampled request, in milliseconds.")
    share = serializers.FloatField(help_text="Share of the attributed request time, 0 to 1.")


@extend_schema_serializer(many=False)
class EndpointTimeSpentResponseSerializer(serializers.Serializer):
    components = TimeSpentComponentSerializer(many=True, help_text="Where the request time goes, largest share first.")
    request_count = serializers.IntegerField(help_text="Requests sampled to compute the breakdown.")
    avg_duration_ms = serializers.FloatField(
        allow_null=True, help_text="Mean duration of the sampled requests, in milliseconds."
    )
    service = serializers.CharField(help_text="The service the endpoint belongs to.")
    endpoint = serializers.CharField(help_text="The endpoint's entry span name.")
    environment = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        help_text="The environment filter the breakdown was computed for: null for every environment, empty for spans with no environment.",
    )
    date_from = serializers.DateTimeField(help_text="Start of the window used.")
    date_to = serializers.DateTimeField(help_text="End of the window used.")


class UsageValuesSerializer(serializers.Serializer):
    log_records = serializers.IntegerField(help_text="Log records stored in the window.")
    log_bytes = serializers.IntegerField(
        help_text="Uncompressed size of the stored log records in bytes. Billing counts logs by this size."
    )
    spans = serializers.IntegerField(help_text="Spans of every kind stored in the window.")
    metric_points = serializers.IntegerField(help_text="Metric data points stored in the window.")
    metric_series = serializers.IntegerField(help_text="Distinct metric series with at least one point in the window.")


class ServiceUsageSerializer(UsageValuesSerializer):
    service_name = serializers.CharField(help_text="The service.name resource attribute.")


@extend_schema_serializer(many=False)
class ServiceUsageResponseSerializer(serializers.Serializer):
    results = ServiceUsageSerializer(
        many=True, help_text="One row per service across logs, traces, and metrics, largest logs size first."
    )
    totals = UsageValuesSerializer(help_text="Totals for the whole window, including services past the row limit.")
    unavailable_signals = serializers.ListField(
        child=serializers.ChoiceField(choices=UsageSignal.choices),
        help_text="Signals that failed to load. Their values are 0 in every row and in the totals.",
    )
    date_from = serializers.DateTimeField(help_text="Start of the window used.")
    date_to = serializers.DateTimeField(help_text="End of the window used.")
