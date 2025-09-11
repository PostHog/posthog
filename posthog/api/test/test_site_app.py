from posthog.test.base import BaseTest

from django.test.client import Client

from rest_framework import status

from posthog.api.site_app import get_site_config_from_schema
from posthog.models import Plugin, PluginConfig, PluginSourceFile


class TestSiteApp(BaseTest):
    def setUp(self):
        super().setUp()
        # it is really important to know that /site_app/ is CSRF exempt. Enforce checking in the client
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def test_site_app(self):
        plugin = Plugin.objects.create(organization=self.team.organization, name="My Plugin", plugin_type="source")
        PluginSourceFile.objects.create(
            plugin=plugin,
            filename="site.ts",
            source="export function inject (){}",
            transpiled="function inject(){}",
            status=PluginSourceFile.Status.TRANSPILED,
        )
        plugin_config = PluginConfig.objects.create(
            plugin=plugin,
            enabled=True,
            order=1,
            team=self.team,
            config={},
            web_token="tokentoken",
        )

        response = self.client.get(
            f"/site_app/{plugin_config.id}/tokentoken/somehash/",
            HTTP_ORIGIN="http://127.0.0.1:8000",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.content.decode("utf-8"),
            f"function inject(){{}}().inject({{config:{{}},posthog:window['__$$ph_site_app_{plugin_config.id}']}})",
        )

    def test_cors_access(self):
        plugin = Plugin.objects.create(organization=self.team.organization, name="My Plugin", plugin_type="source")
        PluginSourceFile.objects.create(
            plugin=plugin,
            filename="site.ts",
            source="export function inject (){}",
            transpiled="function inject(){}",
            status=PluginSourceFile.Status.TRANSPILED,
        )
        plugin_config = PluginConfig.objects.create(
            plugin=plugin,
            enabled=True,
            order=1,
            team=self.team,
            config={},
            web_token="tokentoken",
        )

        unauthenticated_client = Client(enforce_csrf_checks=True)
        unauthenticated_client.logout()
        request_headers = {"HTTP_ACCESS_CONTROL_REQUEST_METHOD": "GET", "HTTP_ORIGIN": "*", "USER_AGENT": "Agent 008"}
        response = unauthenticated_client.get(
            f"/site_app/{plugin_config.id}/tokentoken/somehash/",
            data={},
            follow=False,
            secure=False,
            headers={},
            **request_headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.content.decode("utf-8"),
            f"function inject(){{}}().inject({{config:{{}},posthog:window['__$$ph_site_app_{plugin_config.id}']}})",
        )

    def test_get_site_config_from_schema(self):
        schema: list[dict] = [{"key": "in_site", "site": True}, {"key": "not_in_site"}]
        config = {"in_site": "123", "not_in_site": "12345"}
        self.assertEqual(get_site_config_from_schema(schema, config), {"in_site": "123"})
        self.assertEqual(get_site_config_from_schema(None, None), {})
