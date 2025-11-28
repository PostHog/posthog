from posthog.test.base import BaseTest

from posthog.admin import register_all_admin


class TestAdmin(BaseTest):
    def test_register_admin_models_succeeds(self):
        register_all_admin()
