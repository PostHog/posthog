from typing import Any, cast

from django.db.models import QuerySet

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import exceptions, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import User, UserFacetSettings
from posthog.models.scoping import team_scope
from posthog.permissions import APIScopePermission
from posthog.rate_limit import UserAuthenticationThrottle


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
class UserFacetSettingsViewSet(viewsets.GenericViewSet):
    scope_object = "user"
    serializer_class = UserFacetSettingsSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    throttle_classes = [UserAuthenticationThrottle]
    queryset = User.objects.filter(is_active=True)
    lookup_field = "uuid"

    def get_object(self) -> User:
        lookup_value = self.kwargs[self.lookup_field]
        request_user = cast(User, self.request.user)

        if lookup_value == "@me":
            self.check_object_permissions(self.request, request_user)
            return request_user

        if not request_user.is_staff:
            raise exceptions.PermissionDenied(
                "As a non-staff user you're only allowed to access the `@me` user instance."
            )

        return super().get_object()

    def get_queryset(self) -> QuerySet[User]:
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(id=self.request.user.id)
        return queryset

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
        return team_id
