import json
import secrets
from typing import Any, Dict, Sequence, Type, Union

from django.db.models import Prefetch, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework import mixins, response, serializers, viewsets
from rest_framework.authentication import BaseAuthentication, BasicAuthentication, SessionAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated, OperandHolder, SingleOperandHolder
from rest_framework.request import Request

from posthog.api.insight import InsightSerializer, InsightViewSet
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.constants import INSIGHT_TRENDS
from posthog.event_usage import report_user_action
from posthog.helpers import create_dashboard_from_template
from posthog.models import Dashboard, Insight, Team
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.utils import render_template


class DashboardSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)
    use_template = serializers.CharField(write_only=True, allow_blank=True, required=False)
    use_dashboard = serializers.IntegerField(write_only=True, allow_null=True, required=False)

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
            "use_dashboard",
            "filters",
            "tags",
        ]
        read_only_fields = ("creation_mode",)

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Dashboard:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        team = Team.objects.get(id=self.context["team_id"])
        use_template: str = validated_data.pop("use_template", None)
        use_dashboard: int = validated_data.pop("use_dashboard", None)
        validated_data = self._update_creation_mode(validated_data, use_template, use_dashboard)
        dashboard = Dashboard.objects.create(team=team, **validated_data)

        if use_template:
            try:
                create_dashboard_from_template(use_template, dashboard)
            except AttributeError:
                raise serializers.ValidationError({"use_template": "Invalid value provided."})

        elif use_dashboard:
            try:
                from posthog.api.insight import InsightSerializer

                existing_dashboard = Dashboard.objects.get(id=use_dashboard, team=team)
                existing_dashboard_items = existing_dashboard.items.all()
                for dashboard_item in existing_dashboard_items:
                    override_dashboard_item_data = {
                        "id": None,  # to create a new Insight
                        "dashboard": dashboard.pk,
                        "last_refresh": now(),
                    }
                    insight_serializer = InsightSerializer(
                        data={
                            **InsightSerializer(dashboard_item, context=self.context,).data,
                            **override_dashboard_item_data,
                        },
                        context=self.context,
                    )
                    insight_serializer.is_valid()
                    insight_serializer.save()

            except Dashboard.DoesNotExist:
                raise serializers.ValidationError({"use_dashboard": "Invalid value provided"})

        elif request.data.get("items"):
            for item in request.data["items"]:
                Insight.objects.create(
                    **{key: value for key, value in item.items() if key not in ("id", "deleted", "dashboard", "team")},
                    dashboard=dashboard,
                    team=team,
                )

        report_user_action(
            request.user,
            "dashboard created",
            {
                **dashboard.get_analytics_metadata(),
                "from_template": bool(use_template),
                "template_key": use_template,
                "duplicated": bool(use_dashboard),
                "dashboard_id": use_dashboard,
            },
        )

        return dashboard

    def update(self, instance: Dashboard, validated_data: Dict, *args: Any, **kwargs: Any,) -> Dashboard:
        validated_data.pop("use_template", None)  # Remove attribute if present
        if validated_data.get("is_shared") and not instance.share_token:
            instance.share_token = secrets.token_urlsafe(22)

        instance = super().update(instance, validated_data)

        if "request" in self.context:
            report_user_action(self.context["request"].user, "dashboard updated", instance.get_analytics_metadata())

        return instance

    def add_dive_source_item(self, items: QuerySet, dive_source_id: int):
        item_as_list = list(i for i in items if i.id == dive_source_id)
        if not item_as_list:
            item_as_list = [Insight.objects.get(pk=dive_source_id)]
        others = list(i for i in items if i.id != dive_source_id)
        return item_as_list + others

    def get_items(self, dashboard: Dashboard):
        if self.context["view"].action == "list":
            return None

        items = dashboard.items.filter(deleted=False).order_by("order").all()
        self.context.update({"dashboard": dashboard})

        dive_source_id = self.context["request"].GET.get("dive_source_id")
        if dive_source_id is not None:
            items = self.add_dive_source_item(items, int(dive_source_id))

        #  Make sure all items have an insight set
        # This should have only happened historically
        for item in items:
            if not item.filters.get("insight"):
                item.filters["insight"] = INSIGHT_TRENDS
                item.save()
        return InsightSerializer(items, many=True, context=self.context).data

    def validate(self, data):
        if data.get("use_dashboard", None) and data.get("use_template", None):
            raise serializers.ValidationError("`use_dashboard` and `use_template` cannot be used together")
        return data

    def _update_creation_mode(self, validated_data, use_template: str, use_dashboard: int):
        if use_template:
            return {**validated_data, "creation_mode": "template"}
        if use_dashboard:
            return {**validated_data, "creation_mode": "duplicate"}

        return {**validated_data, "creation_mode": "default"}


class DashboardsViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = Dashboard.objects.all()
    serializer_class = DashboardSerializer
    authentication_classes = [
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
        BasicAuthentication,
    ]
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset().order_by("name")
        if self.action == "list":
            queryset = queryset.filter(deleted=False)
        queryset = queryset.prefetch_related(
            Prefetch("items", queryset=Insight.objects.filter(deleted=False).order_by("order"),)
        )
        return queryset

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        pk = kwargs["pk"]
        queryset = self.get_queryset()
        dashboard = get_object_or_404(queryset, pk=pk)
        dashboard.last_accessed_at = now()
        dashboard.save()
        serializer = DashboardSerializer(dashboard, context={"view": self, "request": request})
        return response.Response(serializer.data)


class LegacyDashboardsViewSet(DashboardsViewSet):
    legacy_team_compatibility = True

    def get_parents_query_dict(self) -> Dict[str, Any]:
        if not self.request.user.is_authenticated or "share_token" in self.request.GET:
            return {}
        return {"team_id": self.team_id}


class SharedDashboardsViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Dashboard.objects.filter(is_shared=True)
    serializer_class = DashboardSerializer
    authentication_classes: Sequence[Type[BaseAuthentication]] = []
    permission_classes: Sequence[Union[Type[BasePermission], OperandHolder, SingleOperandHolder]] = []
    lookup_field = "share_token"


# TODO: Delete this class, as it's been replaced by InsightViewSet
class DashboardItemViewSet(InsightViewSet):
    pass


@xframe_options_exempt
def shared_dashboard(request: HttpRequest, share_token: str):
    dashboard = get_object_or_404(Dashboard, is_shared=True, share_token=share_token)
    shared_dashboard_serialized = {
        "id": dashboard.id,
        "share_token": dashboard.share_token,
        "name": dashboard.name,
        "description": dashboard.description,
        "team_name": dashboard.team.name,
    }

    return render_template(
        "shared_dashboard.html",
        request=request,
        context={"shared_dashboard_serialized": json.dumps(shared_dashboard_serialized)},
    )


class LegacyDashboardItemViewSet(DashboardItemViewSet):
    legacy_team_compatibility = True
