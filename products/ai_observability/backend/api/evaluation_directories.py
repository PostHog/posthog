from typing import cast

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import User
from posthog.permissions import AccessControlPermission

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
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

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError as error:
            raise serializers.ValidationError({"name": "A directory with this name already exists."}) from error

    def perform_destroy(self, instance: EvaluationDirectory) -> None:
        with transaction.atomic():
            evaluations = list(
                Evaluation.objects.filter(team_id=self.team_id, directory_id=instance.id).only(
                    "id", "name", "team_id", "directory_id", "enabled", "status"
                )
            )
            if evaluations:
                Evaluation.objects.filter(
                    team_id=self.team_id, id__in=[evaluation.id for evaluation in evaluations]
                ).update(directory=None, updated_at=timezone.now())
                log_evaluations_moved_to_top_level(evaluations)
            instance.delete()
