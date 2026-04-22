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
from posthog.models.file_system.user_product_list import UserProductList


class UserProductListSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProductList
        fields = [
            "id",
            "product_path",
            "enabled",
            "reason",
            "reason_text",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "product_path",
            "reason",
            "reason_text",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> UserProductList:
        request = self.context["request"]
        team = self.context["get_team"]()

        user_product_list = UserProductList.objects.create(
            team=team,
            user=request.user,
            **validated_data,
        )

        return user_product_list

    def update(self, instance: UserProductList, validated_data: dict[str, Any]) -> UserProductList:
        enabled = validated_data.get("enabled", instance.enabled)

        if enabled:
            validated_data["reason"] = UserProductList.Reason.PRODUCT_INTENT
            validated_data["reason_text"] = ""

        return super().update(instance, validated_data)


class UserProductListViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    queryset = UserProductList.objects.all()
    scope_object = "INTERNAL"
    serializer_class = UserProductListSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team=self.team, user=self.request.user, enabled=True).order_by(Lower("product_path"))

    @action(methods=["PATCH"], detail=False, url_path="update_by_path")
    def update_by_path(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        product_path = request.data.get("product_path")
        if not product_path:
            return Response({"error": "product_path is required"}, status=status.HTTP_400_BAD_REQUEST)

        existing_item, created = UserProductList.objects.get_or_create(
            team=self.team,
            user=cast(User, request.user),
            product_path=product_path,
            defaults={"enabled": True},
        )

        serializer = self.get_serializer(existing_item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(serializer.data, status=status_code)

    @action(methods=["PATCH"], detail=False, url_path="bulk_update")
    def bulk_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        items = request.data.get("items")
        if not isinstance(items, list) or len(items) == 0:
            return Response(
                {"error": "items is required and must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST
            )

        user = cast(User, request.user)
        results = []
        with transaction.atomic():
            for item in items:
                product_path = item.get("product_path")
                enabled = item.get("enabled")
                if not product_path or enabled is None:
                    continue

                existing_item, _created = UserProductList.objects.get_or_create(
                    team=self.team,
                    user=user,
                    product_path=product_path,
                    defaults={"enabled": enabled},
                )

                serializer = self.get_serializer(existing_item, data=item, partial=True)
                serializer.is_valid(raise_exception=True)
                serializer.save()
                results.append(serializer.data)

        return Response({"results": results}, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=False, url_path="seed")
    def seed(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Sync products from colleagues and other projects to fill the user's product list for this team.
        """
        user = cast(User, request.user)
        team = self.team

        UserProductList.backfill_from_other_teams(user, team)
        UserProductList.sync_from_team_colleagues(user, team, count=5)

        # Return all products the user has enabled in this team, not just the ones we created above
        serializer = self.get_serializer(self.safely_get_queryset(self.queryset), many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
