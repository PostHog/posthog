from posthog.test.base import APIBaseTest

from django.test import override_settings


@override_settings(TOOLBAR_OAUTH_ENABLED=True)
class TestAuthorizeAndRedirectOAuth(APIBaseTest):
    pass
