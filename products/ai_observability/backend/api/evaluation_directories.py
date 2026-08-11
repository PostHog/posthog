from typing import Any, Optional, cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import AccessControlPermission
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.ai_observability.backend.activity_logging import log_evaluations_moved_to_top_level
from products.ai_observability.backend.models.evaluation_directories import EvaluationDirectory
from products.ai_observability.backend.models.evaluations import Evaluation


class EvaluationDirectorySerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who created the directory.",
    )
    evaluation_count = serializers.IntegerField(
        read_only=True,
        help_text="Number of active evaluations in the directory.",
    )

    class Meta:
        model = EvaluationDirectory
        fields = ["id", "name", "created_at", "updated_at", "created_by", "evaluation_count"]
        read_only_fields = ["id", "created_at", "updated_at", "created_by", "evaluation_count"]
        extra_kwargs = {
            "name": {"help_text": "Directory name shown in the online evals list."},
        }

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Enter a directory name.")

        team = self.context["get_team"]()
        directories = EvaluationDirectory.objects.for_team(team.id).filter(name__iexact=name)
        if self.instance is not None:
            directories = directories.exclude(pk=self.instance.pk)
        if directories.exists():
            raise serializers.ValidationError("A directory with this name already exists.")
        return name


class EvaluationDirectoryViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ModelViewSet,
):
    scope_object = "evaluation"
    requires_resource_level_access = True
    permission_classes = [IsAuthenticated, AccessControlPermission]
    serializer_class = EvaluationDirectorySerializer
    queryset = EvaluationDirectory.objects.unscoped()
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet[EvaluationDirectory]) -> QuerySet[EvaluationDirectory]:
        return (
            queryset.filter(team_id=self.team_id)
            .select_related("created_by")
            .annotate(evaluation_count=Count("evaluations", filter=Q(evaluations__deleted=False)))
            .order_by("name", "id")
        )

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        try:
            with transaction.atomic():
                directory = serializer.save(team=self.team, created_by=cast(User, self.request.user))
                directory.evaluation_count = 0
        except IntegrityError as error:
            raise serializers.ValidationError({"name": "A directory with this name already exists."}) from error

        self._report_directory_action("llma evaluation directory created", directory.id)

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        directory = cast(EvaluationDirectory, serializer.instance)
        previous_name = directory.name
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError as error:
            raise serializers.ValidationError({"name": "A directory with this name already exists."}) from error

        if directory.name != previous_name:
            self._report_directory_action("llma evaluation directory renamed", directory.id)

    def perform_destroy(self, instance: EvaluationDirectory) -> None:
        # Django clears the primary key on delete(), so hold onto it for the analytics event below.
        directory_id = instance.id
        with transaction.atomic():
            evaluations = list(
                Evaluation.objects.filter(team_id=self.team_id, directory_id=instance.id).only(
                    "id", "name", "team_id", "directory_id", "enabled", "status", "deleted"
                )
            )
            if evaluations:
                Evaluation.objects.filter(
                    team_id=self.team_id, id__in=[evaluation.id for evaluation in evaluations]
                ).update(directory=None, updated_at=timezone.now())
                log_evaluations_moved_to_top_level(evaluations)
            instance.delete()

        self._report_directory_action(
            "llma evaluation directory deleted",
            directory_id,
            # Counting only live evaluations keeps this comparable to the evaluation_count the list API returns,
            # which also excludes soft-deleted evaluations.
            {"evaluations_moved_to_top_level": sum(1 for evaluation in evaluations if not evaluation.deleted)},
        )

    def _report_directory_action(
        self,
        event: str,
        directory_id: UUID,
        properties: Optional[dict[str, Any]] = None,
    ) -> None:
        report_user_action(
            self.request.user,
            event,
            {"directory_id": str(directory_id), **(properties or {})},
            team=self.team,
            request=self.request,
        )
