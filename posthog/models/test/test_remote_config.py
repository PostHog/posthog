from decimal import Decimal
from inline_snapshot import snapshot
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.plugin import Plugin, PluginConfig, PluginSourceFile
from posthog.models.project import Project
from posthog.models.remote_config import RemoteConfig
from posthog.test.base import BaseTest
from django.utils import timezone


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
        self.team.api_token = "phc_12345"  # Easier to test against
        self.team.save()

        # There will always be a config thanks to the signal
        self.remote_config = RemoteConfig.objects.get(team=self.team)


class TestRemoteConfig(_RemoteConfigBase):
    def test_creates_remote_config_immediately(self):
        assert self.remote_config
        assert self.remote_config.updated_at
        assert self.remote_config.synced_at

        assert self.remote_config.config == snapshot(
            {
                "token": "phc_12345",
                "surveys": False,
                "heatmaps": False,
                "siteApps": [],
                "analytics": {"endpoint": "/i/v0/e/"},
                "hasFeatureFlags": False,
                "sessionRecording": False,
                "captureDeadClicks": False,
                "capturePerformance": {"web_vitals": False, "network_timing": True, "web_vitals_allowed_metrics": None},
                "autocapture_opt_out": False,
                "supportedCompression": ["gzip", "gzip-js"],
                "autocaptureExceptions": False,
                "defaultIdentifiedOnly": False,
                "elementsChainAsString": True,
            }
        )

    def test_indicates_if_feature_flags_exist(self):
        assert not self.remote_config.config["hasFeatureFlags"]

        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={},
            name="TestFlag",
            key="test-flag",
            created_by=self.user,
            deleted=True,
        )

        assert not self.remote_config.config["hasFeatureFlags"]
        flag.active = False
        flag.deleted = False
        flag.save()
        self.remote_config.refresh_from_db()
        assert not self.remote_config.config["hasFeatureFlags"]
        flag.active = True
        flag.deleted = False
        flag.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["hasFeatureFlags"]

    def test_capture_dead_clicks_toggle(self):
        self.team.capture_dead_clicks = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["captureDeadClicks"]

    def test_capture_performance_toggle(self):
        self.team.capture_performance_opt_in = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["capturePerformance"]["network_timing"]

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

    def test_session_recording_sample_rate(self):
        self.team.session_recording_opt_in = True
        self.team.session_recording_sample_rate = Decimal("0.5")
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["sessionRecording"]["sampleRate"] == "0.50"


class TestRemoteConfigSync(_RemoteConfigBase):
    def test_does_not_sync_if_no_changes(self):
        synced_at = self.remote_config.synced_at

        assert synced_at
        assert synced_at < timezone.now()
        self.remote_config.config["surveys"] = False
        self.remote_config.sync()
        assert synced_at == self.remote_config.synced_at

        self.remote_config.refresh_from_db()  # Ensure the config object is not referentially the same
        self.remote_config.sync()
        assert synced_at == self.remote_config.synced_at

    def test_syncs_if_changes(self):
        synced_at = self.remote_config.synced_at
        self.remote_config.config["surveys"] = True
        self.remote_config.sync()
        assert synced_at < self.remote_config.synced_at  # type: ignore


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
            window._POSTHOG_CONFIG = {"token": "phc_12345", "surveys": false, "heatmaps": false, "siteApps": [], "analytics": {"endpoint": "/i/v0/e/"}, "hasFeatureFlags": false, "sessionRecording": false, "captureDeadClicks": false, "capturePerformance": {"web_vitals": false, "network_timing": true, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "supportedCompression": ["gzip", "gzip-js"], "autocaptureExceptions": false, "defaultIdentifiedOnly": false, "elementsChainAsString": true};
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
            window._POSTHOG_CONFIG = {"token": "phc_12345", "surveys": false, "heatmaps": false, "siteApps": [], "analytics": {"endpoint": "/i/v0/e/"}, "hasFeatureFlags": false, "sessionRecording": false, "captureDeadClicks": false, "capturePerformance": {"web_vitals": false, "network_timing": true, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "supportedCompression": ["gzip", "gzip-js"], "autocaptureExceptions": false, "defaultIdentifiedOnly": false, "elementsChainAsString": true};
            window._POSTHOG_SITE_APPS = [{ token: 'tokentoken', load: function(posthog) { (function () { return { inject: (data) => console.log('injected!', data)}; })().inject({ config:{}, posthog:posthog }) } },{ token: 'tokentoken', load: function(posthog) { (function () { return { inject: (data) => console.log('injected 2!', data)}; })().inject({ config:{}, posthog:posthog }) } },{ token: 'tokentoken', load: function(posthog) { (function () { return { inject: (data) => console.log('injected but disabled!', data)}; })().inject({ config:{}, posthog:posthog }) } }];
        })();\
"""
        )
