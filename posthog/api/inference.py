from rest_framework import viewsets, serializers, status
from rest_framework.response import Response
from posthog.api.routing import TeamAndOrgViewSetMixin


class InferenceMessageSerializer(serializers.Serializer):
    role = serializers.CharField()
    content = serializers.CharField()


class InferenceSerializer(serializers.Serializer):
    model = serializers.CharField()
    messages = InferenceMessageSerializer(many=True)


class InferenceViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"  # Keep internal until we are happy to release this GA
    log_source = "inference"

    serializer_class = InferenceSerializer
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        return Response(
            {"result": "Inference completed successfully!", "input": validated_data}, status=status.HTTP_200_OK
        )
