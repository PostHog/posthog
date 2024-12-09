import re
from django.http import JsonResponse, Http404, HttpResponse
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView
from posthog.models.remote_config import RemoteConfig


class BaseRemoteConfigAPIView(APIView):
    """
    Base class for RemoteConfig API views.
    """

    authentication_classes = []
    permission_classes = []

    def check_token(self, token: str):
        # Simple check rather than involving a whole serializer
        if len(token) > 200 or not re.match(r"^[a-zA-Z0-9_]+$", token):
            raise ValidationError("Invalid token")
        return token


class RemoteConfigAPIView(BaseRemoteConfigAPIView):
    def get(self, request, token: str, *args, **kwargs):
        try:
            resource = RemoteConfig.get_config_via_token(self.check_token(token))
        except RemoteConfig.DoesNotExist:
            raise Http404()

        return JsonResponse(resource)


class RemoteConfigJSAPIView(BaseRemoteConfigAPIView):
    def get(self, request, token: str, *args, **kwargs):
        try:
            script_content = RemoteConfig.get_config_js_via_token(self.check_token(token))
        except RemoteConfig.DoesNotExist:
            raise Http404()

        return HttpResponse(script_content, content_type="application/javascript")


class RemoteConfigArrayJSAPIView(BaseRemoteConfigAPIView):
    def get(self, request, token: str, *args, **kwargs):
        try:
            script_content = RemoteConfig.get_array_js_via_token(self.check_token(token))
        except RemoteConfig.DoesNotExist:
            raise Http404()

        return HttpResponse(script_content, content_type="application/javascript")
