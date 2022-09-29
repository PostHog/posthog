from django.test.client import Client
from rest_framework import status

from posthog.api.web_js import get_web_config_from_schema, requires_bootloader
from posthog.models import Plugin, PluginConfig, PluginSourceFile
from posthog.test.base import BaseTest


class TestWebJs(BaseTest):
    def setUp(self):
        super().setUp()
        # it is really important to know that /web_js/ is CSRF exempt. Enforce checking in the client
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def test_web_js(self):
        plugin = Plugin.objects.create(organization=self.team.organization, name="My Plugin", plugin_type="source")
        PluginSourceFile.objects.create(
            plugin=plugin,
            filename="web.ts",
            source="export function inject (){}",
            transpiled="function inject(){}",
            status=PluginSourceFile.Status.TRANSPILED,
        )
        plugin_config = PluginConfig.objects.create(
            plugin=plugin, enabled=True, order=1, team=self.team, config={}, web_token="tokentoken"
        )

        response = self.client.get(
            f"/web_js/{plugin_config.id}/tokentoken/",
            HTTP_ORIGIN="http://127.0.0.1:8000",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.content.decode("utf-8"),
            f"function inject(){{}}().inject({{config:{{}},posthog:window['__$$ph_web_js_{plugin_config.id}']}})",
        )

    def test_requires_bootloader(self):
        self.assertFalse(requires_bootloader("a" * 100))
        self.assertTrue(requires_bootloader("a" * 1024))

    def test_get_web_config_from_schema(self):
        schema = [{"key": "in_web", "web": True}, {"key": "not_in_web"}]
        config = {"in_web": "123", "not_in_web": "12345"}
        self.assertEqual(get_web_config_from_schema(schema, config), {"in_web": "123"})
        self.assertEqual(get_web_config_from_schema(None, None), {})
