from posthog.models import Plugin
from posthog.test.base import BaseTest


class TestPlugin(BaseTest):
    def test_default_config_list(self):
        some_plugin: Plugin = Plugin.objects.create(
            organization=self.organization, config_schema=[{"key": "a", "default": 2}, {"key": "b"}]
        )

        default_config = some_plugin.get_default_config()

        self.assertDictEqual(default_config, {"a": 2})

    def test_default_config_dict(self):
        some_plugin: Plugin = Plugin.objects.create(
            organization=self.organization, config_schema={"x": {"default": "z"}, "y": {"default": None}}
        )

        default_config = some_plugin.get_default_config()

        self.assertDictEqual(default_config, {"x": "z"})
