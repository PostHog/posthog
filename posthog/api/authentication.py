from typing import Any

from django.conf import settings
from rest_framework import generics, permissions, serializers

from posthog.settings import print_warning


class AuthenticationSerializer(serializers.Serializer):
    available_backends = serializers.SerializerMethodField()

    def get_available_backends(self, *args):
        github: bool = bool(settings.SOCIAL_AUTH_GITHUB_KEY and settings.SOCIAL_AUTH_GITHUB_SECRET)
        gitlab: bool = bool(settings.SOCIAL_AUTH_GITLAB_KEY and settings.SOCIAL_AUTH_GITLAB_SECRET)
        google: bool = False

        if getattr(settings, "SOCIAL_AUTH_GOOGLE_OAUTH2_KEY", None) and getattr(
            settings, "SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET", None,
        ):
            if settings.MULTI_TENANCY:
                google = True
            else:

                try:
                    from ee.models.license import License
                except ImportError:
                    pass
                else:
                    license = License.objects.first_valid()
                    if license is not None and "google_login" in license.available_features:
                        google = True
                    else:
                        print_warning(["You have Google login set up, but not the required premium PostHog plan!"])

        return {"google-oauth2": google, "github": github, "gitlab": gitlab}


class AuthenticationViewset(generics.RetrieveAPIView):
    serializer_class = AuthenticationSerializer
    permission_classes = (permissions.AllowAny,)

    def get_object(self):
        return {}
