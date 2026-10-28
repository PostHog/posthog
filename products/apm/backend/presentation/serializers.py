"""DRF serializers for apm."""

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from products.apm.backend.facade.api import HealthStatus


class ServicesHealthRequestSerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(
        required=False, help_text="Start of the window, ISO 8601. Defaults to one hour before date_to."
    )
    date_to = serializers.DateTimeField(required=False, help_text="End of the window, ISO 8601. Defaults to now.")
    environment = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=200,
        help_text="Environment to list, as resolved from span resource attributes. Defaults to 'default'.",
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
    environment = serializers.CharField(help_text="The environment the row was computed for.")
    status = serializers.ChoiceField(choices=HealthStatus.choices, help_text="Health band from the error rate.")
    health = HealthRowSerializer(help_text="The health row every surface renders.")
    sparkline = serializers.ListField(
        child=serializers.IntegerField(), help_text="Request counts per bucket across the window, oldest first."
    )


@extend_schema_serializer(many=False)  # drf-spectacular wraps a `list` action's response in an array by default
class ServicesHealthResponseSerializer(serializers.Serializer):
    results = ServiceHealthSerializer(many=True, help_text="One row per service, worst status first.")
    environments = serializers.ListField(child=serializers.CharField(), help_text="Environments seen in the window.")
    environment = serializers.CharField(help_text="The environment the rows were computed for.")
    date_from = serializers.DateTimeField(help_text="Start of the window used.")
    date_to = serializers.DateTimeField(help_text="End of the window used.")


class EndpointHealthSerializer(serializers.Serializer):
    service_name = serializers.CharField(help_text="The service.name resource attribute.")
    endpoint = serializers.CharField(help_text="The entry span name, for example the HTTP route or the job name.")
    environment = serializers.CharField(help_text="The environment the row was computed for.")
    status = serializers.ChoiceField(choices=HealthStatus.choices, help_text="Health band from the error rate.")
    health = HealthRowSerializer(help_text="The health row every surface renders.")


@extend_schema_serializer(many=False)
class EndpointsHealthResponseSerializer(serializers.Serializer):
    results = EndpointHealthSerializer(many=True, help_text="One row per service and endpoint, worst status first.")
    environment = serializers.CharField(help_text="The environment the rows were computed for.")
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
    environment = serializers.CharField(help_text="The environment the map was built for.")
    date_from = serializers.DateTimeField(help_text="Start of the window used.")
    date_to = serializers.DateTimeField(help_text="End of the window used.")
