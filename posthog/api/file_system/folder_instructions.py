from rest_framework import serializers

from posthog.api.file_system.folder_instructions_service import FOLDER_INSTRUCTIONS_MAX_BYTES
from posthog.api.shared import UserBasicSerializer
from posthog.models.file_system.folder_instructions import FileSystemFolderInstructions


def validate_folder_instructions_content(value: str) -> str:
    if len(value.encode("utf-8")) > FOLDER_INSTRUCTIONS_MAX_BYTES:
        raise serializers.ValidationError(
            f"Folder instructions must be {FOLDER_INSTRUCTIONS_MAX_BYTES} bytes or fewer.",
            code="max_size",
        )
    return value


class FolderInstructionsSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, help_text="User who published this version.")

    class Meta:
        model = FileSystemFolderInstructions
        fields = [
            "id",
            "content",
            "version",
            "is_latest",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Unique identifier for this instructions version."},
            "content": {"help_text": "Markdown instructions describing the contents of the folder."},
            "version": {"help_text": "Monotonically increasing version number, starting at 1."},
            "is_latest": {"help_text": "Whether this is the current (latest) version for the folder."},
            "created_at": {"help_text": "When this version was published."},
            "updated_at": {"help_text": "When this version row was last modified."},
        }


class FolderInstructionsVersionSerializer(serializers.ModelSerializer):
    """Version-history entry: metadata only, with the markdown content omitted."""

    created_by = UserBasicSerializer(read_only=True, help_text="User who published this version.")

    class Meta:
        model = FileSystemFolderInstructions
        fields = [
            "id",
            "version",
            "is_latest",
            "created_by",
            "created_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Unique identifier for this instructions version."},
            "version": {"help_text": "Monotonically increasing version number, starting at 1."},
            "is_latest": {"help_text": "Whether this is the current (latest) version for the folder."},
            "created_at": {"help_text": "When this version was published."},
        }


class FolderInstructionsPublishSerializer(serializers.Serializer):
    content = serializers.CharField(
        allow_blank=True,
        help_text="Full markdown instructions to publish as a new version for the folder.",
    )
    base_version = serializers.IntegerField(
        min_value=0,
        required=False,
        help_text=(
            "Latest version you are editing from, for optimistic concurrency. If provided and the "
            "folder's instructions have changed since, the request fails with 409. Use 0 when no "
            "instructions exist yet."
        ),
    )

    def validate_content(self, value: str) -> str:
        return validate_folder_instructions_content(value)
