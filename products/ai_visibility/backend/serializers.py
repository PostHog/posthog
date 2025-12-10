from rest_framework import serializers


class AIVisibilityTriggerSerializer(serializers.Serializer):
    domain = serializers.CharField(max_length=512)
    force = serializers.BooleanField(default=False, required=False)
    run_id = serializers.UUIDField(required=False, allow_null=True)


class AIVisibilityStartedResponseSerializer(serializers.Serializer):
    workflow_id = serializers.CharField()
    run_id = serializers.UUIDField()
    status = serializers.CharField()
    progress_step = serializers.CharField()
    created_at = serializers.DateTimeField()


class AIVisibilityResultResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    run_id = serializers.UUIDField()
    domain = serializers.CharField()
    results = serializers.DictField()
