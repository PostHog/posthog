from inline_snapshot import snapshot
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.plugin import Plugin, PluginConfig, PluginSourceFile
from posthog.models.project import Project
from posthog.models.remote_config import RemoteConfig
from posthog.test.base import BaseTest


class _RemoteConfigBase(BaseTest):
    remote_config: RemoteConfig

    def setUp(self):
        super().setUp()
        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project",
        )
        self.team = team
        # There will always be a config thanks to the signal
        self.remote_config = RemoteConfig.objects.get(team=self.team)


class TestRemoteConfig(_RemoteConfigBase):
    def test_creates_remote_config_immediately(self):
        assert self.remote_config
        assert self.remote_config.updated_at
        assert self.remote_config.synced_at

        assert self.remote_config.config == (
            {
                "supported_compression": ["gzip", "gzip-js"],
                "has_feature_flags": False,
                "capture_dead_clicks": False,
                "capture_performance": {
                    "network_timing": True,
                    "web_vitals": False,
                    "web_vitals_allowed_metrics": None,
                },
                "autocapture_opt_out": False,
                "autocaptureExceptions": False,
                "analytics": {"endpoint": "/i/v0/e/"},
                "elements_chain_as_string": False,
                "session_recording": False,
                "surveys": False,
                "heatmaps": False,
                "default_identified_only": False,
                "site_apps": [],
            }
        )

    def test_indicates_if_feature_flags_exist(self):
        assert not self.remote_config.config["has_feature_flags"]

        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={},
            name="TestFlag",
            key="test-flag",
            created_by=self.user,
            deleted=True,
        )

        assert not self.remote_config.config["has_feature_flags"]
        flag.active = False
        flag.deleted = False
        flag.save()
        self.remote_config.refresh_from_db()
        assert not self.remote_config.config["has_feature_flags"]
        flag.active = True
        flag.deleted = False
        flag.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["has_feature_flags"]

    def test_capture_dead_clicks_toggle(self):
        self.team.capture_dead_clicks = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["capture_dead_clicks"]

    def test_capture_performance_toggle(self):
        self.team.capture_performance_opt_in = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["capture_performance"]["network_timing"]

    def test_autocapture_opt_out_toggle(self):
        self.team.autocapture_opt_out = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["autocapture_opt_out"]

    def test_autocapture_exceptions_toggle(self):
        self.team.autocapture_exceptions_opt_in = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["autocaptureExceptions"] == {"endpoint": "/e/"}


class TestRemoteConfigJS(_RemoteConfigBase):
    def test_renders_js_including_config(self):
        # NOTE: This is a very basic test to check that the JS is rendered correctly
        # It doesn't check the actual contents of the JS, as that changes often but checks some general things
        js = self.remote_config.build_config()
        js = self.remote_config.build_js_config()

        # TODO: Come up with a good way of solidly testing this...
        assert js == snapshot(
            """\
(function() {
            window._POSTHOG_CONFIG = {"surveys": false, "heatmaps": false, "analytics": {"endpoint": "/i/v0/e/"}, "site_apps": [], "has_feature_flags": false, "session_recording": false, "autocapture_opt_out": false, "capture_dead_clicks": false, "capture_performance": {"web_vitals": false, "network_timing": true, "web_vitals_allowed_metrics": null}, "autocaptureExceptions": false, "supported_compression": ["gzip", "gzip-js"], "default_identified_only": false, "elements_chain_as_string": true};
            window._POSTHOG_SITE_APPS = [];
        })();\
"""
        )

    def test_renders_js_including_site_apps(self):
        files = [
            "(function () { return { inject: (data) => console.log('injected!', data)}; })",
            "(function () { return { inject: (data) => console.log('injected 2!', data)}; })",
            "(function () { return { inject: (data) => console.log('injected but disabled!', data)}; })",
        ]

        plugin_configs = []

        for transpiled in files:
            plugin = Plugin.objects.create(organization=self.team.organization, name="My Plugin", plugin_type="source")
            PluginSourceFile.objects.create(
                plugin=plugin,
                filename="site.ts",
                source="IGNORED FOR TESTING",
                transpiled=transpiled,
                status=PluginSourceFile.Status.TRANSPILED,
            )
            plugin_configs.append(
                PluginConfig.objects.create(
                    plugin=plugin,
                    enabled=True,
                    order=1,
                    team=self.team,
                    config={},
                    web_token="tokentoken",
                )
            )

        plugin_configs[2].enabled = False

        self.remote_config.build_config()
        js = self.remote_config.build_js_config()

        # TODO: Come up with a good way of solidly testing this, ideally by running it in an actual browser environment
        assert js == snapshot(
            """\
(function() {
            window._POSTHOG_CONFIG = {"surveys": false, "heatmaps": false, "analytics": {"endpoint": "/i/v0/e/"}, "site_apps": [], "has_feature_flags": false, "session_recording": false, "autocapture_opt_out": false, "capture_dead_clicks": false, "capture_performance": {"web_vitals": false, "network_timing": true, "web_vitals_allowed_metrics": null}, "autocaptureExceptions": false, "supported_compression": ["gzip", "gzip-js"], "default_identified_only": false, "elements_chain_as_string": true};
            window._POSTHOG_SITE_APPS = [{ token: 'tokentoken', load: function(posthog) { (function () { return { inject: (data) => console.log('injected!', data)}; })().inject({ config:{}, posthog:posthog }) } },{ token: 'tokentoken', load: function(posthog) { (function () { return { inject: (data) => console.log('injected 2!', data)}; })().inject({ config:{}, posthog:posthog }) } },{ token: 'tokentoken', load: function(posthog) { (function () { return { inject: (data) => console.log('injected but disabled!', data)}; })().inject({ config:{}, posthog:posthog }) } }];
        })();\
"""
        )
