from django.db.models import QuerySet
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from loginas.utils import is_impersonated_session

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.activity_logging.activity_log import log_activity, Detail
from posthog.models.message_template import MessageTemplate


class MessageTemplateSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = MessageTemplate
        fields = [
            "id",
            "team",
            "name",
            "description",
            "type",
            "content",
            "created_at",
            "created_by",
            "updated_at",
            "deleted",
        ]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]


class MessageTemplateViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "message_template"
    queryset = MessageTemplate.objects.all()
    serializer_class = MessageTemplateSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["type", "deleted"]

    def safely_get_queryset(self) -> QuerySet:
        if not self.action == "partial_update" or self.request.data.get("deleted") is not False:
            # Only include deleted templates if we're un-deleting them
            return super().get_queryset().filter(deleted=False)
        return super().get_queryset()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=self.request.user,
            was_impersonated=is_impersonated_session(self.request),
            item_id=serializer.instance.id,
            scope="MessageTemplate",
            activity="created",
            detail=Detail(name=serializer.instance.name, type=serializer.instance.type),
        )

    def perform_update(self, serializer):
        instance_id = serializer.instance.id
        try:
            before_update = MessageTemplate.objects.get(pk=instance_id)
        except MessageTemplate.DoesNotExist:
            before_update = None

        serializer.save()

        changes = []
        if before_update:
            for field in ["name", "description", "type", "content"]:
                old_value = getattr(before_update, field)
                new_value = getattr(serializer.instance, field)
                if old_value != new_value:
                    changes.append({"field": field, "before": old_value, "after": new_value})

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=self.request.user,
            was_impersonated=is_impersonated_session(self.request),
            item_id=instance_id,
            scope="MessageTemplate",
            activity="updated",
            detail=Detail(
                name=serializer.instance.name,
                type=serializer.instance.type,
                changes=changes,
            ),
        )
