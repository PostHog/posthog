from django.test import SimpleTestCase

from posthog.api.oauth.step_up import STEP_UP_DEFAULT_RESOURCE_SCOPES
from posthog.scopes.oauth import OAUTH_SCOPES_SUPPORTED


class TestStepUpDefaultScopes(SimpleTestCase):
    def test_every_default_scope_is_grantable_over_oauth(self):
        self.assertEqual(STEP_UP_DEFAULT_RESOURCE_SCOPES - set(OAUTH_SCOPES_SUPPORTED), set())
