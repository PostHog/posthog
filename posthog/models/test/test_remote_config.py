from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.project import Project
from posthog.models.remote_config import RemoteConfig
from posthog.test.base import BaseTest


class TestRemoteConfig(BaseTest):
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
