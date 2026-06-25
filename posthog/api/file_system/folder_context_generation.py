from uuid import UUID

from rest_framework import serializers

from products.tasks.backend.facade import api as tasks_facade


class ContextGenerationSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(
        allow_null=True,
        help_text="ID of the Task currently generating this folder's CONTEXT.md, or null if none.",
    )


class ContextGenerationSetSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(
        allow_null=True,
        help_text=(
            "ID of the Task generating this folder's CONTEXT.md. Must reference a Task in the same "
            "team. Set to null to clear the association."
        ),
    )

    def validate_task_id(self, value: UUID | None) -> UUID | None:
        if value is None:
            return None
        team = self.context["folder_team"]
        if not tasks_facade.task_exists(value, team.id):
            raise serializers.ValidationError("No task with this id exists in this team.", code="invalid")
        return value
