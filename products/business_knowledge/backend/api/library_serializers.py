from rest_framework import serializers


class KnowledgeLibrarySerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Library id.")
    name = serializers.CharField(help_text="Library name. Unique in this project, ignoring case.")
    is_default = serializers.BooleanField(
        help_text="True when new sources learned from support tickets join this library. Several libraries can have it."
    )
    source_count = serializers.IntegerField(help_text="How many sources are in this library.")
    repos = serializers.ListField(
        child=serializers.CharField(),
        help_text="Selected repositories in this library that this environment is allowed to read.",
    )


class KnowledgeLibraryCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Name for the new library.")


class KnowledgeLibraryUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, help_text="New name. Omit to keep the current name.")
    source_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Replaces every source in this library. Omit to leave sources unchanged. An empty list removes them all.",
    )
    repos = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text=(
            "Replaces this environment's repositories in the library. "
            "Omit to leave them unchanged. Repositories only another environment allows stay."
        ),
    )
    is_default = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether new sources learned from support tickets join this library. Omit to leave it unchanged. "
            "Sources that are already in the library stay. At least one library must have it."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        if not attrs:
            raise serializers.ValidationError("Provide at least one of `name`, `source_ids`, `repos`, or `is_default`.")
        return attrs
