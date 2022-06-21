import base64

from django.core.exceptions import ValidationError

from posthog.models import Plugin, PluginSourceFile
from posthog.plugins.test.plugin_archives import (
    HELLO_WORLD_PLUGIN_FRONTEND_TSX,
    HELLO_WORLD_PLUGIN_GITHUB_INDEX_JS,
    HELLO_WORLD_PLUGIN_GITHUB_ZIP,
    HELLO_WORLD_PLUGIN_NPM_INDEX_JS,
    HELLO_WORLD_PLUGIN_NPM_TGZ,
    HELLO_WORLD_PLUGIN_PLUGIN_JSON,
    HELLO_WORLD_PLUGIN_PLUGIN_JSON_WITHOUT_MAIN,
    HELLO_WORLD_PLUGIN_RAW_WITH_INDEX_TS_BUT_UNDEFINED_MAIN,
    HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_AND_UNDEFINED_MAIN,
    HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_BUT_FRONTEND_TSX,
    HELLO_WORLD_PLUGIN_RAW_WITHOUT_PLUGIN_JS,
)
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


class TestPluginSourceFile(BaseTest):
    maxDiff = 2000

    def test_sync_from_plugin_archive_from_no_archive_fails(self):
        test_plugin: Plugin = Plugin.objects.create(organization=self.organization, name="Contoso")

        with self.assertNumQueries(0):
            with self.assertRaises(ValidationError) as cm:
                PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(cm.exception.message, f"There is no archive to extract code from in plugin Contoso")

    def test_sync_from_plugin_archive_from_zip_without_plugin_js_fails(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITHOUT_PLUGIN_JS),
        )

        with self.assertNumQueries(0):
            with self.assertRaises(ValidationError) as cm:
                PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(cm.exception.message, f"Could not find plugin.json in plugin Contoso")

    def test_sync_from_plugin_archive_twice_from_zip_with_explicit_index_js_works(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization, name="Contoso", archive=base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1])
        )

        with self.assertNumQueries(13):
            (plugin_json_file, index_ts_file, frontend_tsx_file,) = PluginSourceFile.objects.sync_from_plugin_archive(
                test_plugin
            )

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON)
        assert index_ts_file is not None
        self.assertEqual(index_ts_file.source, HELLO_WORLD_PLUGIN_GITHUB_INDEX_JS)
        self.assertIsNone(frontend_tsx_file)

    def test_sync_from_plugin_archive_twice_from_tgz_with_explicit_index_js_works(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization, name="Contoso", archive=base64.b64decode(HELLO_WORLD_PLUGIN_NPM_TGZ[1])
        )

        # First time - create
        with self.assertNumQueries(13):
            (plugin_json_file, index_ts_file, frontend_tsx_file,) = PluginSourceFile.objects.sync_from_plugin_archive(
                test_plugin
            )

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON)
        assert index_ts_file is not None
        self.assertEqual(index_ts_file.source, HELLO_WORLD_PLUGIN_NPM_INDEX_JS)
        self.assertIsNone(frontend_tsx_file)

        # Second time - update
        with self.assertNumQueries(9):
            (plugin_json_file, index_ts_file, frontend_tsx_file,) = PluginSourceFile.objects.sync_from_plugin_archive(
                test_plugin
            )

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON)
        assert index_ts_file is not None
        self.assertEqual(index_ts_file.source, HELLO_WORLD_PLUGIN_NPM_INDEX_JS)
        self.assertIsNone(frontend_tsx_file)

    def test_sync_from_plugin_archive_twice_from_zip_with_index_ts_works(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITH_INDEX_TS_BUT_UNDEFINED_MAIN),
        )

        with self.assertNumQueries(13):
            (plugin_json_file, index_ts_file, frontend_tsx_file,) = PluginSourceFile.objects.sync_from_plugin_archive(
                test_plugin
            )

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON_WITHOUT_MAIN)
        assert index_ts_file is not None
        self.assertEqual(index_ts_file.source, HELLO_WORLD_PLUGIN_GITHUB_INDEX_JS)
        self.assertIsNone(frontend_tsx_file)

    def test_sync_from_plugin_archive_twice_from_zip_without_index_ts_but_frontend_tsx_works(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_BUT_FRONTEND_TSX),
        )

        with self.assertNumQueries(13):
            (plugin_json_file, index_ts_file, frontend_tsx_file,) = PluginSourceFile.objects.sync_from_plugin_archive(
                test_plugin
            )

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON_WITHOUT_MAIN)
        self.assertIsNone(index_ts_file)
        assert frontend_tsx_file is not None
        self.assertEqual(frontend_tsx_file.source, HELLO_WORLD_PLUGIN_FRONTEND_TSX)

    def test_sync_from_plugin_archive_twice_from_zip_without_any_code_fails(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_AND_UNDEFINED_MAIN),
        )

        with self.assertNumQueries(0):
            with self.assertRaises(ValidationError) as cm:
                PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(cm.exception.message, f"Could not find main file index.js or index.ts in plugin Contoso")

    def test_sync_from_plugin_archive_twice_from_zip_with_index_ts_replaced_by_frontend_tsx_works(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITH_INDEX_TS_BUT_UNDEFINED_MAIN),
        )

        with self.assertNumQueries(13):
            (plugin_json_file, index_ts_file, frontend_tsx_file,) = PluginSourceFile.objects.sync_from_plugin_archive(
                test_plugin
            )

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON_WITHOUT_MAIN)
        assert index_ts_file is not None
        self.assertEqual(index_ts_file.source, HELLO_WORLD_PLUGIN_GITHUB_INDEX_JS)
        self.assertIsNone(frontend_tsx_file)

        test_plugin.archive = base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_BUT_FRONTEND_TSX)
        test_plugin.save()

        with self.assertNumQueries(12):
            (plugin_json_file, index_ts_file, frontend_tsx_file,) = PluginSourceFile.objects.sync_from_plugin_archive(
                test_plugin
            )

        self.assertEqual(PluginSourceFile.objects.count(), 2)  # frontend.tsx replaced by index.ts
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON_WITHOUT_MAIN)
        self.assertIsNone(index_ts_file)
        assert frontend_tsx_file is not None
        self.assertEqual(frontend_tsx_file.source, HELLO_WORLD_PLUGIN_FRONTEND_TSX)
