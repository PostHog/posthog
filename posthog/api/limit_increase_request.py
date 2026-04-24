from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import LimitIncreaseRequest, OrganizationLimitOverride
from posthog.models.limit_increase_request import LimitIncreaseRequestStatus
from posthog.models.user import User
from posthog.resource_limits.registry import REGISTRY, get_definition


class LimitIncreaseRequestSerializer(serializers.ModelSerializer):
    """Customer-visible list/detail/patch for limit increase requests.

    Approve/deny live in Django admin, not on this viewset.
    """

    requested_by = UserBasicSerializer(read_only=True)
    resolved_by = UserBasicSerializer(read_only=True)
    limit_description = serializers.SerializerMethodField(
        help_text="Human-readable description of the limit, sourced from the catalog."
    )
    granted_value = serializers.SerializerMethodField(
        help_text=(
            "The new limit granted after approval. Null means 'unlimited'; the field itself is "
            "only populated for approved requests."
        )
    )
    team_id = serializers.IntegerField(source="team.id", read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)

    class Meta:
        model = LimitIncreaseRequest
        fields = [
            "id",
            "team_id",
            "team_name",
            "limit_key",
            "limit_description",
            "limit_at_first_hit",
            "count_at_first_hit",
            "requested_value",
            "granted_value",
            "justification",
            "status",
            "requested_by",
            "hit_count",
            "last_hit_at",
            "resolved_by",
            "resolved_at",
            "resolution_note",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "team_id",
            "team_name",
            "limit_description",
            "limit_at_first_hit",
            "count_at_first_hit",
            "granted_value",
            "status",
            "requested_by",
            "hit_count",
            "last_hit_at",
            "resolved_by",
            "resolved_at",
            "resolution_note",
            "created_at",
        ]
        extra_kwargs = {
            "limit_key": {
                "help_text": "Namespaced catalog key, e.g. analytics.max_dashboards_per_team.",
            },
            "requested_value": {
                "help_text": "Optional customer hint for the new limit. Null means 'just raise it, PostHog picks'.",
            },
            "justification": {
                "help_text": "Free-text context the customer can edit while the request is pending.",
            },
        }

    def get_limit_description(self, obj: LimitIncreaseRequest) -> str:
        defn = REGISTRY.get(obj.limit_key)
        return defn.description if defn is not None else obj.limit_key

    def get_granted_value(self, obj: LimitIncreaseRequest) -> int | None:
        if obj.status != LimitIncreaseRequestStatus.APPROVED:
            return None
        override = OrganizationLimitOverride.objects.filter(
            team_id=obj.team_id,
            limit_key=obj.limit_key,
        ).first()
        return override.value if override is not None else None

    def validate_limit_key(self, value: str) -> str:
        if value not in REGISTRY:
            raise exceptions.ValidationError(f"Unknown limit key: {value}")
        return value

    def update(
        self,
        instance: LimitIncreaseRequest,
        validated_data: dict[str, Any],
    ) -> LimitIncreaseRequest:
        if instance.status != LimitIncreaseRequestStatus.PENDING:
            raise exceptions.ValidationError("Cannot edit a request that is not pending.")
        allowed_fields = {"justification", "requested_value"}
        unknown = set(validated_data.keys()) - allowed_fields
        if unknown:
            raise exceptions.ValidationError(
                f"These fields cannot be updated: {sorted(unknown)}",
            )
        for field in allowed_fields:
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        instance.save(update_fields=list(validated_data.keys()))
        return instance

    def create(self, validated_data: dict[str, Any]) -> LimitIncreaseRequest:
        from posthog.resource_limits.request_upsert import upsert_limit_increase_request

        # Pre-emptive request from the settings scene before they've hit the
        # limit. We don't know current count yet — use 0 as a placeholder.
        team = self.context["get_team"]()
        user = self.context["request"].user
        assert isinstance(user, User)

        defn = get_definition(validated_data["limit_key"])
        if defn.default is None:
            raise exceptions.ValidationError(
                "This limit is currently unlimited, no need to request an increase.",
            )

        request_obj = upsert_limit_increase_request(
            team=team,
            limit_key=validated_data["limit_key"],
            limit=defn.default,
            current_count=0,
            user=user,
        )
        if "justification" in validated_data:
            request_obj.justification = validated_data["justification"]
        if "requested_value" in validated_data:
            request_obj.requested_value = validated_data["requested_value"]
        if "justification" in validated_data or "requested_value" in validated_data:
            request_obj.save(update_fields=["justification", "requested_value"])
        return request_obj


@extend_schema(tags=["resource_limits"])
class LimitIncreaseRequestViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    serializer_class = LimitIncreaseRequestSerializer
    queryset = LimitIncreaseRequest.objects.all()
    lookup_field = "id"
    ordering = "-last_hit_at"

    def safely_get_queryset(self, queryset):
        return queryset.select_related("requested_by", "resolved_by").order_by(self.ordering)
