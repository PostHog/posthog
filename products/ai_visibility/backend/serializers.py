from rest_framework import serializers


class AIVisibilityTriggerSerializer(serializers.Serializer):
    domain = serializers.CharField(max_length=512)


class AIVisibilityTriggerResponseSerializer(serializers.Serializer):
    workflow_id = serializers.CharField()
    status = serializers.CharField()
