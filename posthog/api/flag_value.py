from drf_spectacular.utils import OpenApiResponse
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import FeatureFlag


class FlagValueQuerySerializer(serializers.Serializer):
    key = serializers.CharField(required=False, help_text="The flag ID", allow_blank=True)


class FlagValueItemSerializer(serializers.Serializer):
    name = serializers.JSONField()


class FlagValueResponseSerializer(serializers.Serializer):
    results = FlagValueItemSerializer(many=True)
    refreshing = serializers.BooleanField()


class FlagValueViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    API endpoint for getting possible values for feature flags.
    Returns true/false for boolean flags and only variant keys for multivariate flags.
    """

    permission_classes = [IsAuthenticated]
    scope_object = "feature_flag"

    @validated_request(
        query_serializer=FlagValueQuerySerializer,
        responses={
            200: OpenApiResponse(response=FlagValueResponseSerializer),
            400: OpenApiResponse(response=serializers.DictField()),
            404: OpenApiResponse(response=serializers.DictField()),
        },
    )
    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        """
        Get possible values for a feature flag.

        Query parameters:
        - key: The flag ID (required)
        Returns:

        - Array of objects with 'name' field containing possible values
        """
        flag_id = request.validated_query_data.get("key")

        if not flag_id:
            return response.Response({"error": "Missing flag ID parameter"}, status=400)

        try:
            flag_id_int = int(flag_id)
        except (ValueError, TypeError):
            return response.Response({"error": "Invalid flag ID - must be a valid integer"}, status=400)

        try:
            flag = FeatureFlag.objects.get(team=self.team, id=flag_id_int)
        except FeatureFlag.DoesNotExist:
            return response.Response({"error": "Feature flag not found"}, status=404)

        # Check if this is a multivariate flag with variants
        multivariate_config = flag.filters.get("multivariate")
        has_variants = multivariate_config and multivariate_config.get("variants")

        if has_variants:
            # For multivariate flags, only return the variant keys
            values = []
            for variant in multivariate_config["variants"]:
                variant_key = variant.get("key")
                if variant_key:
                    values.append({"name": variant_key})
        else:
            # For boolean flags, return true and false
            values = [{"name": True}, {"name": False}]

        return response.Response({"results": values, "refreshing": False})
