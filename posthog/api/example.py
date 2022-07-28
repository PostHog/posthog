from typing import Any

from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

"""
Shamelessly stolen from https://medium.com/django-rest-framework/django-rest-framework-viewset-when-you-don-t-have-a-model-335a0490ba6f
"""


class Task(object):
    def __init__(self, **kwargs):
        for field in ("id", "name", "owner", "status"):
            setattr(self, field, kwargs.get(field, None))


tasks = {
    1: Task(id=1, name="Demo", owner="xordoquy", status="Done"),
    2: Task(id=2, name="Model less demo", owner="xordoquy", status="Ongoing"),
    3: Task(id=3, name="Sleep more", owner="xordoquy", status="New"),
}


class TaskSerializer(serializers.Serializer):  # Not model serializer
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=256)
    owner = serializers.CharField(max_length=256)

    def create(self, validated_data):
        return Task(id=None, **validated_data)

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        return instance


class TaskViewSet(viewsets.ViewSet):
    # Required for the Browsable API renderer to have a nice form.
    serializer_class = TaskSerializer

    def list(self, request: Request, *args: Any, **kwargs: Any):
        serializer = TaskSerializer(instance=tasks.values(), many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        serializer = TaskSerializer(instance=tasks.get(kwargs["pk"]), many=False)
        return Response(serializer.data)
