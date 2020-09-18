import secrets
from datetime import datetime
from distutils.util import strtobool
from typing import Any, Dict, List

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db.models import Prefetch, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from rest_framework import authentication, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed

from posthog.models import Dashboard, DashboardItem, Filter
from posthog.utils import PersonalAPIKeyAuthentication, PublicTokenAuthentication, generate_cache_key, render_template


class DashboardSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()  # type: ignore

    class Meta:
        model = Dashboard
        fields = ["id", "name", "pinned", "items", "created_at", "created_by", "is_shared", "share_token", "deleted"]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Dashboard:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        team = request.user.team
        dashboard = Dashboard.objects.create(team=team, **validated_data)

        if request.data.get("items"):
            for item in request.data["items"]:
                DashboardItem.objects.create(
                    **{key: value for key, value in item.items() if key not in ("id", "deleted", "dashboard", "team")},
                    dashboard=dashboard,
                    team=team,
                )

        return dashboard

    def update(  # type: ignore
        self, instance: Dashboard, validated_data: Dict, *args: Any, **kwargs: Any
    ) -> Dashboard:
        if validated_data.get("is_shared") and not instance.share_token:
            instance.share_token = secrets.token_urlsafe(22)
        return super().update(instance, validated_data)

    def get_items(self, dashboard: Dashboard):
        if self.context["view"].action == "list":
            return None
        items = dashboard.items.filter(deleted=False).order_by("order").all()
        return DashboardItemSerializer(items, many=True).data


class DashboardsViewSet(viewsets.ModelViewSet):
    queryset = Dashboard.objects.all()
    serializer_class = DashboardSerializer
    authentication_classes = [
        PublicTokenAuthentication,
        PersonalAPIKeyAuthentication,
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
            Prefetch("items", queryset=DashboardItem.objects.filter(deleted=False).order_by("order"),)
        )

        if self.request.user.is_anonymous:
            if self.request.GET.get("share_token"):
                return queryset.filter(share_token=self.request.GET["share_token"])
            else:
                raise AuthenticationFailed(detail="You're not logged in or forgot to add a share_token.")

        return queryset.filter(team=self.request.user.team)

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        pk = kwargs["pk"]
        queryset = self.get_queryset()
        dashboard = get_object_or_404(queryset, pk=pk)
        dashboard.last_accessed_at = now()
        dashboard.save()
        serializer = DashboardSerializer(dashboard, context={"view": self, "request": request})
        return response.Response(serializer.data)


class DashboardItemSerializer(serializers.ModelSerializer):
    result = serializers.SerializerMethodField()

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
            "created_at",
            "saved",
            "created_by",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> DashboardItem:

        request = self.context["request"]
        team = request.user.team
        validated_data.pop("last_refresh", None)  # last_refresh sometimes gets sent if dashboard_item is duplicated

        if not validated_data.get("dashboard", None):
            dashboard_item = DashboardItem.objects.create(team=team, created_by=request.user, **validated_data)
            return dashboard_item
        elif validated_data["dashboard"].team == team:
            filter_data = validated_data.pop("filters", None)
            filters = Filter(data=filter_data) if filter_data else None
            dashboard_item = DashboardItem.objects.create(
                team=team, last_refresh=now(), filters=filters.to_dict() if filters else {}, **validated_data
            )
            return dashboard_item
        else:
            raise serializers.ValidationError("Dashboard not found")

    def get_result(self, dashboard_item: DashboardItem):
        if not dashboard_item.filters:
            return None
        filter = Filter(data=dashboard_item.filters)
        cache_key = generate_cache_key(filter.toJSON() + "_" + str(dashboard_item.team_id))
        result = cache.get(cache_key)
        if not result or result.get("task_id", None):
            return None
        return result["result"]


class DashboardItemsViewSet(viewsets.ModelViewSet):
    queryset = DashboardItem.objects.all()
    serializer_class = DashboardItemSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":  # type: ignore
            queryset = queryset.filter(deleted=False)
            queryset = self._filter_request(self.request, queryset)

        order = self.request.GET.get("order", None)
        if order:
            queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by("order")

        return queryset.filter(team=self.request.user.team)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "saved":
                queryset = queryset.filter(saved=bool(strtobool(str(request.GET["saved"]))))
            elif key == "user":
                queryset = queryset.filter(created_by=request.user)
            elif key == "insight":
                queryset = queryset.filter(filters__insight=request.GET["insight"])

        return queryset

    @action(methods=["patch"], detail=False)
    def layouts(self, request):
        team = request.user.team

        for data in request.data["items"]:
            self.queryset.filter(team=team, pk=data["id"]).update(layouts=data["layouts"])

        serializer = self.get_serializer(self.queryset.filter(team=team), many=True)
        return response.Response(serializer.data)


def shared_dashboard(request: HttpRequest, share_token: str):
    dashboard = get_object_or_404(Dashboard, is_shared=True, share_token=share_token)
    return render_template(
        "shared_dashboard.html", request=request, context={"dashboard": dashboard, "team_name": dashboard.team.name},
    )
