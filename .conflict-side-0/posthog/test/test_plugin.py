import base64

from posthog.test.base import BaseTest, QueryMatchingTest, snapshot_postgres_queries

from django.core import exceptions

from posthog.models import Plugin, PluginSourceFile
from posthog.plugins.test.plugin_archives import (
    HELLO_WORLD_PLUGIN_FRONTEND_TSX,
    HELLO_WORLD_PLUGIN_GITHUB_INDEX_JS,
    HELLO_WORLD_PLUGIN_GITHUB_ZIP,
    HELLO_WORLD_PLUGIN_NPM_INDEX_JS,
    HELLO_WORLD_PLUGIN_NPM_TGZ,
    HELLO_WORLD_PLUGIN_PLUGIN_JSON,
    HELLO_WORLD_PLUGIN_PLUGIN_JSON_WITHOUT_MAIN,
    HELLO_WORLD_PLUGIN_RAW_SUBDIR,
    HELLO_WORLD_PLUGIN_RAW_WITH_INDEX_TS_BUT_UNDEFINED_MAIN,
    HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_AND_UNDEFINED_MAIN,
    HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_BUT_FRONTEND_TSX,
    HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_BUT_SITE_TS,
    HELLO_WORLD_PLUGIN_RAW_WITHOUT_PLUGIN_JS,
    HELLO_WORLD_PLUGIN_SITE_TS,
)


class TestPlugin(BaseTest):
    def test_default_config_list(self):
        some_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            config_schema=[{"key": "a", "default": 2}, {"key": "b"}],
        )

        default_config = some_plugin.get_default_config()

        self.assertDictEqual(default_config, {"a": 2})

    def test_default_config_dict(self):
        some_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            config_schema={"x": {"default": "z"}, "y": {"default": None}},
        )

        default_config = some_plugin.get_default_config()

        self.assertDictEqual(default_config, {"x": "z"})


class TestPluginSourceFile(BaseTest, QueryMatchingTest):
    maxDiff = 2000

    @snapshot_postgres_queries
    def test_sync_from_plugin_archive_from_no_archive_fails(self):
        test_plugin: Plugin = Plugin.objects.create(organization=self.organization, name="Contoso")

        with self.assertRaises(exceptions.ValidationError) as cm:
            PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(
            cm.exception.message,
            f"There is no archive to extract code from in plugin Contoso",
        )

    @snapshot_postgres_queries
    def test_sync_from_plugin_archive_from_zip_without_plugin_js_fails(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITHOUT_PLUGIN_JS),
        )

        with self.assertRaises(exceptions.ValidationError) as cm:
            PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(cm.exception.message, f"Could not find plugin.json in plugin Contoso")

    @snapshot_postgres_queries
    def test_sync_from_plugin_archive_from_zip_with_explicit_index_js_works(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_GITHUB_ZIP[1]),
        )

        (
            plugin_json_file,
            index_ts_file,
            frontend_tsx_file,
            site_ts_file,
        ) = PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON)
        assert index_ts_file is not None
        self.assertEqual(index_ts_file.source, HELLO_WORLD_PLUGIN_GITHUB_INDEX_JS)
        self.assertIsNone(frontend_tsx_file)
        self.assertIsNone(site_ts_file)

    @snapshot_postgres_queries
    def test_sync_from_plugin_archive_from_tgz_with_explicit_index_js_works(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_NPM_TGZ[1]),
        )

        # First time - create
        (
            plugin_json_file,
            index_ts_file,
            frontend_tsx_file,
            site_ts_file,
        ) = PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON)
        assert index_ts_file is not None
        self.assertEqual(index_ts_file.source, HELLO_WORLD_PLUGIN_NPM_INDEX_JS)
        self.assertIsNone(frontend_tsx_file)
        self.assertIsNone(site_ts_file)

        # Second time - update
        (
            plugin_json_file,
            index_ts_file,
            frontend_tsx_file,
            site_ts_file,
        ) = PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON)
        assert index_ts_file is not None
        self.assertEqual(index_ts_file.source, HELLO_WORLD_PLUGIN_NPM_INDEX_JS)
        self.assertIsNone(frontend_tsx_file)
        self.assertIsNone(site_ts_file)

    @snapshot_postgres_queries
    def test_sync_from_plugin_archive_from_zip_with_index_ts_works(self):
        self.assertFalse(self.team.inject_web_apps)
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITH_INDEX_TS_BUT_UNDEFINED_MAIN),
        )

        (
            plugin_json_file,
            index_ts_file,
            frontend_tsx_file,
            site_ts_file,
        ) = PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON_WITHOUT_MAIN)
        assert index_ts_file is not None
        self.assertEqual(index_ts_file.source, HELLO_WORLD_PLUGIN_GITHUB_INDEX_JS)
        self.assertIsNone(frontend_tsx_file)
        self.assertIsNone(site_ts_file)
        self.assertFalse(self.team.inject_web_apps)

    @snapshot_postgres_queries
    def test_sync_from_plugin_archive_from_zip_without_index_ts_but_frontend_tsx_works(self):
        self.assertFalse(self.team.inject_web_apps)
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_BUT_FRONTEND_TSX),
        )

        (
            plugin_json_file,
            index_ts_file,
            frontend_tsx_file,
            site_ts_file,
        ) = PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON_WITHOUT_MAIN)
        self.assertIsNone(index_ts_file)
        self.assertIsNone(site_ts_file)
        assert frontend_tsx_file is not None
        self.assertEqual(frontend_tsx_file.source, HELLO_WORLD_PLUGIN_FRONTEND_TSX)
        self.assertFalse(self.team.inject_web_apps)

    @snapshot_postgres_queries
    def test_sync_from_plugin_archive_from_zip_without_index_ts_but_site_ts_works(self):
        self.assertFalse(self.team.inject_web_apps)
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_BUT_SITE_TS),
        )

        (
            plugin_json_file,
            index_ts_file,
            frontend_tsx_file,
            site_ts_file,
        ) = PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON_WITHOUT_MAIN)
        self.assertIsNone(index_ts_file)
        self.assertIsNone(frontend_tsx_file)
        assert site_ts_file is not None
        self.assertEqual(site_ts_file.source, HELLO_WORLD_PLUGIN_SITE_TS)
        self.assertEqual(site_ts_file.status, PluginSourceFile.Status.TRANSPILED)
        assert site_ts_file.transpiled is not None and len(site_ts_file.transpiled) > 0

    @snapshot_postgres_queries
    def test_sync_from_plugin_archive_from_zip_without_any_code_fails(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_AND_UNDEFINED_MAIN),
        )

        with self.assertRaises(exceptions.ValidationError) as cm:
            PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(
            cm.exception.message,
            f"Could not find main file index.js or index.ts in plugin Contoso",
        )

    @snapshot_postgres_queries
    def test_sync_from_plugin_archive_twice_from_zip_with_index_ts_replaced_by_frontend_tsx_works(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITH_INDEX_TS_BUT_UNDEFINED_MAIN),
        )

        (
            plugin_json_file,
            index_ts_file,
            frontend_tsx_file,
            site_ts_file,
        ) = PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON_WITHOUT_MAIN)
        assert index_ts_file is not None
        self.assertEqual(index_ts_file.source, HELLO_WORLD_PLUGIN_GITHUB_INDEX_JS)
        self.assertIsNone(frontend_tsx_file)

        test_plugin.archive = base64.b64decode(HELLO_WORLD_PLUGIN_RAW_WITHOUT_ANY_INDEX_TS_BUT_FRONTEND_TSX)
        test_plugin.save()

        (
            plugin_json_file,
            index_ts_file,
            frontend_tsx_file,
            site_ts_file,
        ) = PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(PluginSourceFile.objects.count(), 2)  # frontend.tsx replaced by index.ts
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON_WITHOUT_MAIN)
        self.assertIsNone(index_ts_file)
        assert frontend_tsx_file is not None
        self.assertEqual(frontend_tsx_file.source, HELLO_WORLD_PLUGIN_FRONTEND_TSX)
        self.assertEqual(frontend_tsx_file.status, PluginSourceFile.Status.TRANSPILED)
        assert frontend_tsx_file.transpiled is not None and len(frontend_tsx_file.transpiled) > 0

    @snapshot_postgres_queries
    def test_sync_from_plugin_archive_with_subdir_works(self):
        test_plugin: Plugin = Plugin.objects.create(
            organization=self.organization,
            name="Contoso",
            archive=base64.b64decode(HELLO_WORLD_PLUGIN_RAW_SUBDIR),
            url="https://www.github.com/PostHog/helloworldplugin/tree/main/app",
        )

        (
            plugin_json_file,
            index_ts_file,
            frontend_tsx_file,
            site_ts_file,
        ) = PluginSourceFile.objects.sync_from_plugin_archive(test_plugin)

        self.assertEqual(PluginSourceFile.objects.count(), 2)
        self.assertEqual(plugin_json_file.source, HELLO_WORLD_PLUGIN_PLUGIN_JSON)
        assert index_ts_file is not None
        self.assertEqual(index_ts_file.source, HELLO_WORLD_PLUGIN_GITHUB_INDEX_JS)
        self.assertIsNone(frontend_tsx_file)
