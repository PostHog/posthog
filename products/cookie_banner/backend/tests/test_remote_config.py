import json

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.constants import AvailableFeature
from posthog.models.remote_config import RemoteConfig
from posthog.models.scoping import team_scope

from products.cookie_banner.backend.models import CookieBannerConfig


class TestCookieBannerRemoteConfig(BaseTest):
    def _create_config(self, **kwargs) -> CookieBannerConfig:
        with team_scope(self.team.id):
            return CookieBannerConfig.objects.create(team=self.team, **kwargs)

    def _site_apps_js(self) -> str:
        return "\n".join(RemoteConfig(team=self.team).build_config()["siteAppsJS"])

    def test_enabled_banner_is_included_in_site_apps_js(self) -> None:
        self._create_config(enabled=True, appearance={"title": "Cookie time"})
        js = self._site_apps_js()
        assert "id: 'cookie-banner'" in js
        assert json.dumps("Cookie time") in js
        assert "opt_in_capturing" in js

    def test_disabled_or_absent_banner_is_not_included(self) -> None:
        assert "cookie-banner" not in self._site_apps_js()
        self._create_config(enabled=False)
        assert "cookie-banner" not in self._site_apps_js()

    def test_unknown_appearance_keys_never_reach_the_payload(self) -> None:
        self._create_config(enabled=True, appearance={"artStyle": "not-a-style", "evil": "<script>"})
        js = self._site_apps_js()
        assert "evil" not in js
        assert "not-a-style" not in js  # falls back to the default art style

    def test_white_label_requires_entitlement_at_build_time(self) -> None:
        # whiteLabel snuck into the DB without the entitlement must not remove branding
        self._create_config(enabled=True, appearance={"whiteLabel": True})
        assert '"whiteLabel": false' in self._site_apps_js()

        self.organization.available_product_features = [
            {"key": AvailableFeature.WHITE_LABELLING, "name": AvailableFeature.WHITE_LABELLING}
        ]
        self.organization.save()
        assert '"whiteLabel": true' in self._site_apps_js()

    def test_saving_config_schedules_remote_config_rebuild(self) -> None:
        with patch("posthog.models.remote_config._update_team_remote_config") as mock_update:
            with self.captureOnCommitCallbacks(execute=True):
                self._create_config(enabled=True)
            mock_update.assert_called_once_with(self.team.id)
