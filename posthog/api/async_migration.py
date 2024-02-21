import structlog
from rest_framework import response, serializers, viewsets
from rest_framework.decorators import action
from semantic_version.base import Version

from posthog.async_migrations.runner import (
    MAX_CONCURRENT_ASYNC_MIGRATIONS,
    is_posthog_version_compatible,
)
from posthog.async_migrations.setup import get_async_migration_definition
from posthog.async_migrations.utils import (
    force_stop_migration,
    rollback_migration,
    trigger_migration,
)
from posthog.constants import FROZEN_POSTHOG_VERSION
from posthog.models.async_migration import (
    AsyncMigration,
    AsyncMigrationError,
    MigrationStatus,
    get_all_running_async_migrations,
)
from posthog.models.instance_setting import get_instance_setting
from posthog.permissions import IsStaffUser
from rest_framework.permissions import IsAuthenticated

logger = structlog.get_logger(__name__)


class AsyncMigrationErrorsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AsyncMigrationError
        fields = ["id", "description", "created_at"]
        read_only_fields = ["id", "description", "created_at"]


class AsyncMigrationSerializer(serializers.ModelSerializer):
    error_count = serializers.SerializerMethodField()
    parameter_definitions = serializers.SerializerMethodField()
    is_available = serializers.SerializerMethodField()

    class Meta:
        model = AsyncMigration
        fields = [
            "id",
            "name",
            "description",
            "progress",
            "status",
            "current_operation_index",
            "current_query_id",
            "celery_task_id",
            "started_at",
            "finished_at",
            "posthog_max_version",
            "posthog_min_version",
            "parameters",
            "error_count",
            "parameter_definitions",
            "is_available",
        ]
        read_only_fields = [
            "id",
            "name",
            "description",
            "progress",
            "status",
            "current_operation_index",
            "current_query_id",
            "celery_task_id",
            "started_at",
            "finished_at",
            "posthog_max_version",
            "posthog_min_version",
            "error_count",
            "parameter_definitions",
            "is_available",
        ]

    def get_error_count(self, async_migration: AsyncMigration):
        return AsyncMigrationError.objects.filter(async_migration=async_migration).count()

    def get_parameter_definitions(self, async_migration: AsyncMigration):
        try:
            definition = get_async_migration_definition(async_migration.name)
            # Ignore typecasting logic for parameters
            return {key: param[:2] for key, param in definition.parameters.items()}
        except LookupError as e:
            logger.warn(f"Parameters for {async_migration.name} not available error: {e}")
        return {}

    def get_is_available(self, async_migration: AsyncMigration):
        return (
            get_instance_setting("ASYNC_MIGRATIONS_IGNORE_POSTHOG_VERSION")
            or Version(async_migration.posthog_min_version) <= FROZEN_POSTHOG_VERSION
        )


class AsyncMigrationsViewset(viewsets.ModelViewSet):
    queryset = AsyncMigration.objects.all().order_by("name")
    permission_classes = [IsAuthenticated, IsStaffUser]
    serializer_class = AsyncMigrationSerializer

    @action(methods=["POST"], detail=True)
    def trigger(self, request, **kwargs):
        if get_all_running_async_migrations().count() >= MAX_CONCURRENT_ASYNC_MIGRATIONS:
            return response.Response(
                {
                    "success": False,
                    "error": f"No more than {MAX_CONCURRENT_ASYNC_MIGRATIONS} async migration can run at once.",
                },
                status=400,
            )

        migration_instance = self.get_object()

        if not is_posthog_version_compatible(
            migration_instance.posthog_min_version,
            migration_instance.posthog_max_version,
        ):
            return response.Response(
                {
                    "success": False,
                    "error": f"Can't run migration. Minimum PostHog version: {migration_instance.posthog_min_version}. Maximum PostHog version: {migration_instance.posthog_max_version}",
                },
                status=400,
            )

        migration_instance.status = MigrationStatus.Starting
        migration_instance.parameters = request.data.get("parameters", {})
        migration_instance.save()

        trigger_migration(migration_instance)
        return response.Response({"success": True}, status=200)

    @action(methods=["POST"], detail=True)
    def resume(self, request, **kwargs):
        migration_instance = self.get_object()
        if migration_instance.status != MigrationStatus.Errored:
            return response.Response(
                {
                    "success": False,
                    "error": "Can't resume a migration that isn't in errored state",
                },
                status=400,
            )

        migration_instance.status = MigrationStatus.Running
        migration_instance.parameters = request.data.get("parameters", {})
        migration_instance.save()

        trigger_migration(migration_instance, fresh_start=False)
        return response.Response({"success": True}, status=200)

    def _force_stop(self, rollback: bool):
        migration_instance = self.get_object()
        if migration_instance.status not in [
            MigrationStatus.Running,
            MigrationStatus.Starting,
        ]:
            return response.Response(
                {
                    "success": False,
                    "error": "Can't stop a migration that isn't running.",
                },
                status=400,
            )
        force_stop_migration(migration_instance, rollback=rollback)
        return response.Response({"success": True}, status=200)

    # DANGEROUS! Can cause another task to be lost
    @action(methods=["POST"], detail=True)
    def force_stop(self, request, **kwargs):
        return self._force_stop(rollback=True)

    # DANGEROUS! Can cause another task to be lost
    @action(methods=["POST"], detail=True)
    def force_stop_without_rollback(self, request, **kwargs):
        return self._force_stop(rollback=False)

    @action(methods=["POST"], detail=True)
    def rollback(self, request, **kwargs):
        migration_instance = self.get_object()
        if migration_instance.status != MigrationStatus.Errored:
            return response.Response(
                {
                    "success": False,
                    "error": "Can't rollback a migration that isn't in errored state.",
                },
                status=400,
            )

        rollback_migration(migration_instance)
        return response.Response({"success": True}, status=200)

    @action(methods=["POST"], detail=True)
    def force_rollback(self, request, **kwargs):
        migration_instance = self.get_object()
        if migration_instance.status != MigrationStatus.CompletedSuccessfully:
            return response.Response(
                {
                    "success": False,
                    "error": "Can't force rollback a migration that did not complete successfully.",
                },
                status=400,
            )

        rollback_migration(migration_instance)
        return response.Response({"success": True}, status=200)

    @action(methods=["GET"], detail=True)
    def errors(self, request, **kwargs):
        migration_instance = self.get_object()
        return response.Response(
            [
                AsyncMigrationErrorsSerializer(e).data
                for e in AsyncMigrationError.objects.filter(async_migration=migration_instance).order_by("-created_at")
            ]
        )
