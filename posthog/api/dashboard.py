from rest_framework import request, response, serializers, viewsets, authentication
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from posthog.models import Dashboard, DashboardItem, Filter
from typing import Dict, Any, List
from django.db.models import QuerySet, Prefetch
from django.shortcuts import get_object_or_404
from datetime import datetime
from posthog.utils import render_template, generate_cache_key
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest
from django.core.cache import cache
import secrets


class PublicTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request: request.Request):
        if (
            request.GET.get("share_token")
            and request.parser_context
            and request.parser_context.get("kwargs")
        ):
            dashboard = Dashboard.objects.filter(
                share_token=request.GET.get("share_token"),
                pk=request.parser_context["kwargs"].get("pk"),
            )
            if not dashboard.exists():
                raise AuthenticationFailed(detail="Dashboard doesnt exist")
            return (AnonymousUser(), None)
        return None


class DashboardSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()  # type: ignore

    class Meta:
        model = Dashboard
        fields = [
            "id",
            "name",
            "pinned",
            "items",
            "created_at",
            "created_by",
            "is_shared",
            "share_token",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Dashboard:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        team = request.user.team_set.get()
        dashboard = Dashboard.objects.create(team=team, **validated_data)

        if request.data.get("items"):
            for item in request.data["items"]:
                DashboardItem.objects.create(
                    **{
                        key: value
                        for key, value in item.items()
                        if key not in ("id", "deleted", "dashboard", "team")
                    },
                    dashboard=dashboard,
                    team=team,
                )

        return dashboard

    def update(
        self, instance: Dashboard, validated_data: Dict, *args: Any, **kwargs: Any
    ) -> Dashboard:
        if validated_data.get("is_shared") and not instance.share_token:
            instance.share_token = secrets.token_urlsafe(22)
        return super().update(instance, validated_data)

    def get_items(self, dashboard: Dashboard):
        if self.context["view"].action == "list":
            return None
        items = dashboard.items.all()
        return DashboardItemSerializer(items, many=True).data


class DashboardsViewSet(viewsets.ModelViewSet):
    queryset = Dashboard.objects.all()
    serializer_class = DashboardSerializer
    authentication_classes = [
        PublicTokenAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]
    # Empty list means we can allow users to not be authenticated.
    permission_classes = []  # type: ignore

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset().order_by("name")
        if self.action == "list":  # type: ignore
            queryset = queryset.filter(deleted=False)
        queryset = queryset.prefetch_related(
            Prefetch(
                "items",
                queryset=DashboardItem.objects.filter(deleted=False).order_by("order"),
            )
        )

        if self.request.user.is_anonymous:
            if self.request.GET.get("share_token"):
                return queryset.filter(share_token=self.request.GET["share_token"])
            else:
                raise AuthenticationFailed(
                    detail="You're not logged in or forgot to add a share_token."
                )

        return queryset.filter(team=self.request.user.team_set.get())


class DashboardItemSerializer(serializers.ModelSerializer):
    result = serializers.SerializerMethodField()  # type: ignore

    class Meta:
        model = DashboardItem
        fields = [
            "id",
            "name",
            "filters",
            "order",
            "type",
            "deleted",
            "dashboard",
            "layouts",
            "color",
            "last_refresh",
            "refreshing",
            "result",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> DashboardItem:
        request = self.context["request"]
        team = request.user.team_set.get()
        if validated_data["dashboard"].team == team:
            dashboard_item = DashboardItem.objects.create(
                team=team, last_refresh=datetime.now(), **validated_data
            )
            return dashboard_item
        else:
            raise serializers.ValidationError("Dashboard not found")

    def get_result(self, dashboard_item: DashboardItem):
        if not dashboard_item.filters:
            return None
        filter = Filter(data=dashboard_item.filters)
        cache_key = generate_cache_key(
            filter.toJSON() + "_" + str(dashboard_item.team_id)
        )
        result = cache.get(cache_key)
        if not result:
            return None
        return result["result"]


class DashboardItemsViewSet(viewsets.ModelViewSet):
    queryset = DashboardItem.objects.all()
    serializer_class = DashboardItemSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":  # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset.filter(team=self.request.user.team_set.get()).order_by("order")

    @action(methods=["patch"], detail=False)
    def layouts(self, request):
        team = request.user.team_set.get()

        for data in request.data["items"]:
            self.queryset.filter(team=team, pk=data["id"]).update(
                layouts=data["layouts"]
            )

        serializer = self.get_serializer(self.queryset, many=True)
        return response.Response(serializer.data)


def shared_dashboard(request: HttpRequest, share_token: str):
    dashboard = get_object_or_404(Dashboard, is_shared=True, share_token=share_token)
    return render_template(
        "shared_dashboard.html",
        request=request,
        context={"dashboard_id": dashboard.pk, "share_token": dashboard.share_token},
    )
