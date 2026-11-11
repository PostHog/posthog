from django.test import SimpleTestCase

from posthog.api.oauth.step_up import STEP_UP_DEFAULT_RESOURCE_SCOPES
from posthog.scopes import get_oauth_scopes_supported


class TestStepUpDefaultScopes(SimpleTestCase):
    def test_every_default_scope_is_grantable_over_oauth(self):
        self.assertEqual(STEP_UP_DEFAULT_RESOURCE_SCOPES - set(get_oauth_scopes_supported()), set())
