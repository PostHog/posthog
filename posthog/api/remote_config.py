from django.http import JsonResponse, Http404, HttpResponse
from rest_framework.views import APIView
from posthog.models.remote_config import RemoteConfig


class BaseRemoteConfigAPIView(APIView):
    """
    Base class for RemoteConfig API views.
    """

    authentication_classes = []
    permission_classes = []

    def get_object(self, token: str) -> RemoteConfig:
        try:
            return RemoteConfig.objects.get(team__api_token=token)
        except RemoteConfig.DoesNotExist:
            raise Http404()


class RemoteConfigAPIView(BaseRemoteConfigAPIView):
    def get(self, request, token: str, *args, **kwargs):
        resource = self.get_object(token)
        return JsonResponse(resource.config)


class RemoteConfigJSAPIView(BaseRemoteConfigAPIView):
    def get(self, request, token: str, *args, **kwargs):
        resource = self.get_object(token)
        script_content = resource.build_js_config()
        return HttpResponse(script_content, content_type="application/javascript")


class RemoteConfigArrayJSAPIView(BaseRemoteConfigAPIView):
    def get(self, request, token: str, *args, **kwargs):
        resource = self.get_object(token)
        script_content = resource.build_array_js_config()
        return HttpResponse(script_content, content_type="application/javascript")
