from rest_framework import response, serializers, viewsets
from rest_framework.decorators import action

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.special_migration import MigrationStatus, SpecialMigration, get_all_running_special_migrations
from posthog.permissions import StaffUser
from posthog.special_migrations.runner import MAX_CONCURRENT_SPECIAL_MIGRATIONS, is_posthog_version_compatible
from posthog.special_migrations.utils import force_rollback_migration, force_stop_migration, trigger_migration


class SpecialMigrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpecialMigration
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
            "last_error",
            "posthog_max_version",
            "posthog_min_version",
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
            "last_error",
            "posthog_max_version",
            "posthog_min_version",
        ]


class SpecialMigrationsViewset(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = SpecialMigration.objects.all()
    permission_classes = [StaffUser]
    serializer_class = SpecialMigrationSerializer

    @action(methods=["POST"], detail=True)
    def trigger(self, request, **kwargs):
        if len(get_all_running_special_migrations()) >= MAX_CONCURRENT_SPECIAL_MIGRATIONS:
            return response.Response(
                {
                    "success": False,
                    "error": f"No more than {MAX_CONCURRENT_SPECIAL_MIGRATIONS} special migration can run at once.",
                },
                status=400,
            )

        migration_instance = self.get_object()

        if not is_posthog_version_compatible(
            migration_instance.posthog_min_version, migration_instance.posthog_max_version
        ):
            return response.Response(
                {
                    "success": False,
                    "error": f"Can't run migration. Minimum PostHog version: {migration_instance.posthog_min_version}. Maximum PostHog version: {migration_instance.posthog_max_version}",
                },
                status=400,
            )

        migration_instance.status = MigrationStatus.Starting
        migration_instance.save()

        trigger_migration(migration_instance)
        return response.Response({"success": True}, status=200)

    # DANGEROUS! Can cause another task to be lost
    @action(methods=["POST"], detail=True)
    def force_stop(self, request, **kwargs):
        migration_instance = self.get_object()
        if migration_instance.status != MigrationStatus.Running:
            return response.Response(
                {"success": False, "error": "Can't stop a migration that isn't running.",}, status=400,
            )
        force_stop_migration(migration_instance)
        return response.Response({"success": True}, status=200)

    @action(methods=["POST"], detail=True)
    def force_rollback(self, request, **kwargs):
        migration_instance = self.get_object()
        if migration_instance.status != MigrationStatus.CompletedSuccessfully:
            return response.Response(
                {"success": False, "error": "Can't force rollback a migration that did not complete successfully.",},
                status=400,
            )

        force_rollback_migration(migration_instance)
        return response.Response({"success": True}, status=200)
