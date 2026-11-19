from rest_framework import serializers


class KnowledgeKeySerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Project secret API key id.")
    label = serializers.CharField(help_text="Name of the key. Unique in this project.")  # type: ignore[assignment]
    mask_value = serializers.CharField(allow_null=True, help_text="First and last characters of the key.")
    value = serializers.CharField(
        allow_null=True,
        help_text="The key itself. Returned once, in the response that creates the key. Null everywhere else.",
    )
    created_at = serializers.DateTimeField(help_text="When the key was created.")
    last_used_at = serializers.DateTimeField(
        allow_null=True, help_text="When the key last made a request, to the hour. Null when it never has."
    )
    is_limited = serializers.BooleanField(
        help_text="True when the key reads one library. False when it reads all business knowledge in the project."
    )
    library_id = serializers.UUIDField(
        allow_null=True,
        help_text=(
            "The library a limited key reads. Null on a limited key means its library was deleted, "
            "so the key reads nothing."
        ),
    )


class KnowledgeKeyCreateSerializer(serializers.Serializer):
    label = serializers.CharField(  # type: ignore[assignment]
        max_length=40, help_text="Name for the key. Must be unique in this project."
    )
    library_id = serializers.UUIDField(
        allow_null=True,
        help_text=(
            "The library this key reads. Send null for a key that reads all business knowledge in the project. "
            "It cannot be changed later."
        ),
    )
