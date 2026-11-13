from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.user_settings_viewset import UserSettingsViewSet
from posthog.models import User, UserFacetSettings
from posthog.models.scoping import team_scope
from posthog.permissions import check_team_within_credential_organizations


class UserFacetSettingsEntrySerializer(serializers.Serializer):
    key = serializers.CharField(
        help_text=(
            "The log or span attribute key this facet is based on — for example `http.status_code` or `k8s.pod.name`."
        )
    )
    source_type = serializers.ChoiceField(
        choices=["attribute", "resourceAttribute"],
        help_text=(
            "Where the key lives: `attribute` for a plain log/span attribute, `resourceAttribute` for an "
            "OpenTelemetry resource attribute."
        ),
    )


class UserFacetSettingsSerializer(serializers.Serializer):
    custom_facets = UserFacetSettingsEntrySerializer(
        many=True,
        help_text=(
            "Ordered list of custom facets the user has pinned for this product, within the current team. "
            "Send the full list to replace the existing set."
        ),
    )


PRODUCT_PARAMETER = OpenApiParameter(
    name="product",
    type=str,
    location=OpenApiParameter.QUERY,
    required=True,
    enum=UserFacetSettings.Product.values,
    description="Which product's custom facets to read or update.",
)


@extend_schema(extensions={"x-product": "platform_features"})
@extend_schema_view(
    retrieve=extend_schema(
        description=(
            "Get the authenticated user's custom facets for a product, within the current team. Pass `@me` as the UUID."
        ),
        parameters=[PRODUCT_PARAMETER],
        responses={200: UserFacetSettingsSerializer},
    ),
    partial_update=extend_schema(
        description=(
            "Replace the authenticated user's custom facets for a product, within the current team. "
            "Pass `@me` as the UUID."
        ),
        parameters=[PRODUCT_PARAMETER],
        request=UserFacetSettingsSerializer,
        responses={200: UserFacetSettingsSerializer},
    ),
)
class UserFacetSettingsViewSet(UserSettingsViewSet):
    serializer_class = UserFacetSettingsSerializer

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        product = self._get_product()
        team_id = self._get_team_id(instance)

        # Read-only: most users never pin a facet, so a missing row reads as an empty list
        # instead of creating one per user/team/product on every rail mount.
        with team_scope(team_id):
            custom_facets = (
                UserFacetSettings.objects.filter(user=instance, team_id=team_id, product=product)
                .values_list("custom_facets", flat=True)
                .first()
            )
        return Response({"custom_facets": custom_facets or []})

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        product = self._get_product()
        team_id = self._get_team_id(instance)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with team_scope(team_id):
            settings, _ = UserFacetSettings.objects.update_or_create(
                user=instance,
                team_id=team_id,
                product=product,
                defaults={"custom_facets": serializer.validated_data["custom_facets"]},
            )

        return Response({"custom_facets": settings.custom_facets})

    def _get_product(self) -> str:
        product = self.request.query_params.get("product")
        if product not in UserFacetSettings.Product.values:
            raise serializers.ValidationError(
                f"`product` query parameter is required and must be one of: "
                f"{', '.join(UserFacetSettings.Product.values)}."
            )
        return product

    def _get_team_id(self, instance: User) -> int:
        # The id column on the user row is enough — dereferencing `current_team` would fetch the
        # whole (wide) Team row on every request.
        team_id = instance.current_team_id
        if not team_id:
            raise serializers.ValidationError("Current team is required to manage custom facets.")
        check_team_within_credential_organizations(self.request, team_id)
        return team_id
