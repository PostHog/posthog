import secrets
from typing import Any, Dict, Optional

import posthoganalytics
from django.db.models import Model, Prefetch, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework import authentication, response, serializers, viewsets
from rest_framework.exceptions import AuthenticationFailed, NotFound
from rest_framework.request import Request

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication, PublicTokenAuthentication
from posthog.helpers import create_dashboard_from_template
from posthog.models import Dashboard, Insight, Team
from posthog.utils import get_safe_cache, render_template


class DashboardSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)
    use_template = serializers.CharField(write_only=True, allow_blank=True, required=False)

    class Meta:
        model = Dashboard
        fields = [
            "id",
            "name",
            "description",
            "pinned",
            "items",
            "created_at",
            "created_by",
            "is_shared",
            "share_token",
            "deleted",
            "creation_mode",
            "use_template",
            "filters",
            "tags",
        ]
        read_only_fields = ("creation_mode",)

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Dashboard:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        team = Team.objects.get(id=self.context["team_id"])
        use_template: str = validated_data.pop("use_template", None)
        creation_mode = "template" if use_template else "default"
        dashboard = Dashboard.objects.create(team=team, creation_mode=creation_mode, **validated_data)

        if use_template:
            try:
                create_dashboard_from_template(use_template, dashboard)
            except AttributeError:
                raise serializers.ValidationError({"use_template": "Invalid value provided."})

        elif request.data.get("items"):
            for item in request.data["items"]:
                Insight.objects.create(
                    **{key: value for key, value in item.items() if key not in ("id", "deleted", "dashboard", "team")},
                    dashboard=dashboard,
                    team=team,
                )

        posthoganalytics.capture(
            request.user.distinct_id,
            "dashboard created",
            {**dashboard.get_analytics_metadata(), "from_template": bool(use_template), "template_key": use_template},
        )

        return dashboard

    def update(self, instance: Dashboard, validated_data: Dict, *args: Any, **kwargs: Any,) -> Dashboard:
        validated_data.pop("use_template", None)  # Remove attribute if present
        if validated_data.get("is_shared") and not instance.share_token:
            instance.share_token = secrets.token_urlsafe(22)

        instance = super().update(instance, validated_data)

        if "request" in self.context:
            posthoganalytics.capture(
                self.context["request"].user.distinct_id, "dashboard updated", instance.get_analytics_metadata()
            )

        return instance

    def get_items(self, dashboard: Dashboard):
        if self.context["view"].action == "list":
            return None
        items = dashboard.items.filter(deleted=False).order_by("order").all()
        self.context.update({"dashboard": dashboard})
        return InsightSerializer(items, many=True, context=self.context).data


class DashboardsViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    legacy_team_compatibility = True  # to be moved to a separate Legacy*ViewSet Class

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
        if self.action == "list":
            queryset = queryset.filter(deleted=False)
        queryset = queryset.prefetch_related(
            Prefetch("items", queryset=Insight.objects.filter(deleted=False).order_by("order"),)
        )
        if self.request.GET.get("share_token"):
            return queryset.filter(share_token=self.request.GET["share_token"])
        elif self.request.user.is_authenticated and not self.request.user.team:
            raise NotFound()
        elif not self.request.user.is_authenticated or "team_id" not in self.get_parents_query_dict():
            raise AuthenticationFailed(detail="You're not logged in, but also not using add share_token.")

        return queryset

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        pk = kwargs["pk"]
        queryset = self.get_queryset()
        dashboard = get_object_or_404(queryset, pk=pk)
        dashboard.last_accessed_at = now()
        dashboard.save()
        serializer = DashboardSerializer(dashboard, context={"view": self, "request": request})
        return response.Response(serializer.data)

    def get_parents_query_dict(self) -> Dict[str, Any]:  # to be moved to a separate Legacy*ViewSet Class
        if not self.request.user.is_authenticated or "share_token" in self.request.GET or not self.request.user.team:
            return {}
        return {"team_id": self.request.user.team.id}


class InsightSerializer(serializers.ModelSerializer):
    result = serializers.SerializerMethodField()
    last_refresh = serializers.SerializerMethodField()
    _get_result: Optional[Dict[str, Any]] = None

    class Meta:
        model = Insight
        fields = [
            "id",
            "name",
            "description",
            "filters",
            "filters_hash",
            "order",
            "deleted",
            "dashboard",
            "layouts",
            "color",
            "last_refresh",
            "refreshing",
            "result",
            "is_sample",
            "saved",
            "created_at",
            "created_by",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Insight:
        request = self.context["request"]
        team = Team.objects.get(id=self.context["team_id"])
        validated_data.pop("last_refresh", None)  # last_refresh sometimes gets sent if insight is duplicated

        if not validated_data.get("dashboard", None):
            insight = Insight.objects.create(team=team, created_by=request.user, **validated_data)
            return insight
        elif validated_data["dashboard"].team == team:
            created_by = validated_data.pop("created_by", request.user)
            insight = Insight.objects.create(team=team, last_refresh=now(), created_by=created_by, **validated_data)
            return insight
        else:
            raise serializers.ValidationError("Dashboard not found")

    def update(self, instance: Model, validated_data: Dict, **kwargs) -> Insight:
        # Remove is_sample if it's set as user has altered the sample configuration
        validated_data.setdefault("is_sample", False)
        return super().update(instance, validated_data)

    def get_result(self, insight: Insight):
        # If it's more than a day old, don't return anything
        if insight.last_refresh and (now() - insight.last_refresh).days > 0:
            return None

        if not insight.filters_hash:
            return None

        result = get_safe_cache(insight.filters_hash)
        if not result or result.get("task_id", None):
            return None
        return result.get("result")

    def get_last_refresh(self, insight: Insight):
        if self.get_result(insight):
            return insight.last_refresh
        insight.last_refresh = None
        insight.save()
        return None

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["filters"] = instance.dashboard_filters(dashboard=self.context.get("dashboard"))
        return representation


@xframe_options_exempt
def shared_dashboard(request: HttpRequest, share_token: str):
    dashboard = get_object_or_404(Dashboard, is_shared=True, share_token=share_token)
    return render_template(
        "shared_dashboard.html", request=request, context={"dashboard": dashboard, "team_name": dashboard.team.name},
    )
