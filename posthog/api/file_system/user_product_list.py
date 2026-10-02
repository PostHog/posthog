from typing import Any, cast

from django.db import transaction
from django.db.models import QuerySet
from django.db.models.functions import Lower

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.models.file_system.starred_products import star_custom_products
from posthog.models.file_system.user_product_list import UserProductList, user_has_custom_products


class UserProductListSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProductList
        fields = [
            "id",
            "product_path",
            "enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "product_path",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> UserProductList:
        request = self.context["request"]
        team = self.context["get_team"]()

        user = cast(User, request.user)
        had_custom_products = user_has_custom_products(user)
        user_product_list = UserProductList.objects.create(
            team=team,
            user=user,
            **validated_data,
        )
        if user_product_list.enabled:
            star_custom_products(user, team, [user_product_list.product_path], had_custom_products=had_custom_products)

        return user_product_list


class UserProductListViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    queryset = UserProductList.objects.all()
    scope_object = "INTERNAL"
    serializer_class = UserProductListSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team=self.team, user=self.request.user, enabled=True).order_by(Lower("product_path"))

    @action(methods=["PATCH"], detail=False, url_path="bulk_update")
    def bulk_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        items = request.data.get("items")
        if not isinstance(items, list) or len(items) == 0:
            return Response(
                {"error": "items is required and must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST
            )

        user = cast(User, request.user)
        had_custom_products = user_has_custom_products(user)
        results = []
        enabled_paths = []
        with transaction.atomic():
            for item in items:
                product_path = item.get("product_path")
                enabled = item.get("enabled")
                if not product_path or enabled is None:
                    continue

                existing_item, created = UserProductList.objects.get_or_create(
                    team=self.team,
                    user=user,
                    product_path=product_path,
                    defaults={"enabled": enabled},
                )
                was_enabled = existing_item.enabled and not created

                serializer = self.get_serializer(existing_item, data=item, partial=True)
                serializer.is_valid(raise_exception=True)
                serializer.save()
                results.append(serializer.data)
                if existing_item.enabled and not was_enabled:
                    enabled_paths.append(product_path)

        star_custom_products(user, self.team, enabled_paths, had_custom_products=had_custom_products)
        return Response({"results": results}, status=status.HTTP_200_OK)
