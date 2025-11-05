from rest_framework import request, response, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import FeatureFlag


class FlagValueViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    API endpoint for getting possible values for feature flags.
    Returns true/false for boolean flags and variant keys for multivariate flags.
    """

    permission_classes = [IsAuthenticated]
    scope_object = "feature_flag"

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        """
        Get possible values for a feature flag.

        Query parameters:
        - key: The flag ID (required)
        Returns:

        - Array of objects with 'name' field containing possible values
        """
        flag_id = request.GET.get(
            "key"
        )  # "key" here is the property key, which happens to be the flag id for flag dependencies.

        if not flag_id:
            return response.Response({"error": "Missing flag ID parameter"}, status=400)

        try:
            # Convert flag_id to integer if it's a string
            flag_id_int = int(flag_id)
        except (ValueError, TypeError):
            return response.Response({"error": "Invalid flag ID - must be a valid integer"}, status=400)

        try:
            flag = FeatureFlag.objects.get(team=self.team, id=flag_id_int, deleted=False)
        except FeatureFlag.DoesNotExist:
            return response.Response({"error": "Feature flag not found"}, status=404)

        # Always include true and false for any flag
        values = [{"name": True}, {"name": False}]

        # Add variant keys if this is a multivariate flag
        if flag.filters.get("multivariate") and flag.filters["multivariate"].get("variants"):
            for variant in flag.filters["multivariate"]["variants"]:
                variant_key = variant.get("key")
                if variant_key:
                    values.append({"name": variant_key})

        return response.Response(values)
