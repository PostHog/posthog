from rest_framework import serializers


class AIVisibilityTriggerSerializer(serializers.Serializer):
    domain = serializers.CharField(max_length=512)


class AIVisibilityStartedResponseSerializer(serializers.Serializer):
    workflow_id = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()


class AIVisibilityResultResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    run_id = serializers.UUIDField()
    domain = serializers.CharField()
    results = serializers.DictField()
