from rest_framework import response, serializers, viewsets
from rest_framework.decorators import action

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.special_migration import MigrationStatus, SpecialMigration, get_all_running_special_migrations
from posthog.permissions import StaffUser
from posthog.special_migrations.runner import start_special_migration
from posthog.tasks.special_migrations import run_special_migration

# allow users to set this?
# important to prevent us taking up too many celery workers
MAX_CONCURRENT_SPECIAL_MIGRATIONS = 1


class SpecialMigrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpecialMigration
        fields = [
            "id",
            "name",
            "progress",
            "status",
            "current_operation_index",
            "current_query_id",
            "celery_task_id",
            "started_at",
            "finished_at",
            "error",
        ]
        read_only_fields = [
            "id",
            "name",
            "progress",
            "status",
            "current_operation_index",
            "current_query_id",
            "celery_task_id",
            "started_at",
            "finished_at",
            "error",
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
                    "error": f"No more than {MAX_CONCURRENT_SPECIAL_MIGRATIONS} special migrations can run at once",
                },
                status=400,
            )
        sm = self.get_object()
        task = run_special_migration.delay(sm.name)
        sm.celery_task_id = str(task.id)
        sm.save()
        return response.Response({"success": True}, status=201)

    @action(methods=["POST"], detail=True)
    def stop(self, request, **kwargs):
        pass

    @action(methods=["POST"], detail=True)
    def rollback(self, request, **kwargs):
        pass
