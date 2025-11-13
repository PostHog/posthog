from typing import Any

from django.db.models import QuerySet
from django.db.models.functions import Lower

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.file_system.user_product_list import UserProductList


class UserProductListSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProductList
        fields = [
            "id",
            "product_path",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def update(self, instance: UserProductList, validated_data: dict[str, Any]) -> UserProductList:
        instance.team_id = self.context["team_id"]
        instance.user = self.context["request"].user
        return super().update(instance, validated_data)

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> UserProductList:
        request = self.context["request"]
        team = self.context["get_team"]()
        user_product_list = UserProductList.objects.create(
            team=team,
            user=request.user,
            **validated_data,
        )
        return user_product_list


class BulkUpdateUserProductListSerializer(serializers.Serializer):
    products = serializers.ListField(
        child=serializers.DictField(
            child=serializers.CharField(),
        )
    )

    def validate_products(self, value):
        for product in value:
            if "product_path" not in product:
                raise serializers.ValidationError("Each product must have a 'product_path' field.")
        return value


class UserProductListViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    queryset = UserProductList.objects.all()
    scope_object = "user_product_list"
    serializer_class = UserProductListSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team=self.team, user=self.request.user, enabled=True).order_by(Lower("product_path"))

    @action(methods=["POST"], detail=False, url_path="bulk_update")
    def bulk_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = BulkUpdateUserProductListSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        products_data = serializer.validated_data["products"]

        existing_products = {
            item.product_path: item for item in UserProductList.objects.filter(team=self.team, user=request.user)
        }

        product_paths_to_keep = {product["product_path"] for product in products_data}

        for product_path in product_paths_to_keep:
            if product_path not in existing_products:
                UserProductList.objects.create(
                    team=self.team,
                    user=request.user,
                    product_path=product_path,
                    enabled=True,
                )

        for product_path, item in existing_products.items():
            if product_path not in product_paths_to_keep:
                item.enabled = False
                item.save()

        return Response(status=status.HTTP_204_NO_CONTENT)
