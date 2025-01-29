from rest_framework import viewsets, serializers, status
from rest_framework.response import Response
from posthog.api.routing import TeamAndOrgViewSetMixin
from together import Together
from posthog.models.filters.mixins.utils import cached_property


SUPPORTED_MODELS = ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"]


class InferenceMessageSerializer(serializers.Serializer):
    role = serializers.CharField()
    content = serializers.CharField()


class InferenceSerializer(serializers.Serializer):
    model = serializers.ChoiceField(choices=SUPPORTED_MODELS)
    stream = serializers.BooleanField(required=False)
    messages = InferenceMessageSerializer(many=True)


class InferenceViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    # Keep internal until we are happy to release this GA
    # See https://docs.google.com/document/d/1MFTGrWZpX0ehA-i7XcfIvnkk4b8hRmXcS8lHWRsvel0
    scope_object = "INTERNAL"

    log_source = "inference"

    serializer_class = InferenceSerializer
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        messages = validated_data["messages"]
        model = validated_data["model"]
        stream = False  # TODO handle streaming

        together_response = self._together_client.chat.completions.create(
            model=model,
            messages=messages,
            stream=stream,
        )

        choices = [
            {"message": {"content": choice.message.content, "role": choice.message.role}}
            for choice in together_response.choices
        ]
        response = {
            "choices": choices,
            "stream": stream,
        }

        return Response(response, status=status.HTTP_200_OK)

    @cached_property
    def _together_client(self):
        return Together()
