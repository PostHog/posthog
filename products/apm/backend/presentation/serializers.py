"""DRF serializers for apm."""

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


class HealthRowSerializer(serializers.Serializer):
    request_rate = serializers.FloatField(allow_null=True, help_text="Requests per second over the window.")
    error_rate = serializers.FloatField(allow_null=True, help_text="Share of requests with an error status, 0 to 1.")
    p95_ms = serializers.FloatField(allow_null=True, help_text="95th percentile request duration in milliseconds.")
    span_count = serializers.IntegerField(help_text="Requests counted in the window.")
    error_count = serializers.IntegerField(help_text="Requests with an error status in the window.")


class ServiceHealthSerializer(serializers.Serializer):
    service_name = serializers.CharField(help_text="The service.name resource attribute.")
    environment = serializers.CharField(help_text="The environment the row was computed for.")
    status = serializers.ChoiceField(
        choices=[s.value for s in HealthStatus], help_text="Health band from the error rate."
    )
    health = HealthRowSerializer(help_text="The health row every surface renders.")
    sparkline = serializers.ListField(
        child=serializers.IntegerField(), help_text="Request counts per bucket across the window, oldest first."
    )


class ServicesHealthResponseSerializer(serializers.Serializer):
    results = ServiceHealthSerializer(many=True, help_text="One row per service, worst status first.")
    environments = serializers.ListField(child=serializers.CharField(), help_text="Environments seen in the window.")
    environment = serializers.CharField(help_text="The environment the rows were computed for.")
    date_from = serializers.DateTimeField(help_text="Start of the window used.")
    date_to = serializers.DateTimeField(help_text="End of the window used.")
