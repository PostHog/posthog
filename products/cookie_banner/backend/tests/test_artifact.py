import json

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.constants import AvailableFeature
from posthog.models.remote_config import RemoteConfig
from posthog.models.scoping import team_scope
from posthog.storage.hypercache import HyperCacheStoreMissing

from products.cookie_banner.backend.artifact import (
    _sanitize_categories,
    _sanitize_translations,
    build_cookie_banner_artifact,
)
from products.cookie_banner.backend.models import CookieBannerConfig


class TestCookieBannerArtifact(BaseTest):
    def _create_config(self, **kwargs) -> CookieBannerConfig:
        with team_scope(self.team.id):
            return CookieBannerConfig.objects.create(team=self.team, **kwargs)

    def _artifact_js(self) -> str:
        artifact = build_cookie_banner_artifact(self.team)
        assert not isinstance(artifact, HyperCacheStoreMissing)
        return artifact["js"]

    def test_enabled_banner_builds_standalone_runtime(self) -> None:
        self._create_config(enabled=True, appearance={"title": "Cookie time"})
        js = self._artifact_js()
        assert json.dumps("Cookie time") in js
        # The team token must be baked in: it derives posthog-js's native consent key,
        # which is what gates the SDK before it initializes
        assert json.dumps(self.team.api_token) in js
        assert "__ph_opt_in_out_" in js
        assert "data-ph-consent" in js

    def test_disabled_or_absent_banner_stores_missing(self) -> None:
        assert isinstance(build_cookie_banner_artifact(self.team), HyperCacheStoreMissing)
        self._create_config(enabled=False)
        assert isinstance(build_cookie_banner_artifact(self.team), HyperCacheStoreMissing)

    def test_unknown_appearance_keys_never_reach_the_payload(self) -> None:
        self._create_config(enabled=True, appearance={"artStyle": "not-a-style", "evil": "<script>"})
        js = self._artifact_js()
        assert "evil" not in js
        assert "not-a-style" not in js  # falls back to the default art style

    def test_categories_reach_the_payload_sanitized(self) -> None:
        self._create_config(
            enabled=True,
            appearance={"categories": [{"key": "Bad Key!", "label": "x"}, {"key": "chat", "label": "Chat"}]},
        )
        js = self._artifact_js()
        assert "Bad Key!" not in js
        assert json.dumps("chat") in js
        # analytics is re-added even when junk data dropped it: the runtime requires it
        assert '"key": "analytics"' in js

    def test_white_label_requires_entitlement_at_build_time(self) -> None:
        # whiteLabel snuck into the DB without the entitlement must not remove branding
        self._create_config(enabled=True, appearance={"whiteLabel": True})
        assert '"whiteLabel": false' in self._artifact_js()

        self.organization.available_product_features = [
            {"key": AvailableFeature.WHITE_LABELLING, "name": AvailableFeature.WHITE_LABELLING}
        ]
        self.organization.save()
        assert '"whiteLabel": true' in self._artifact_js()

    def test_translations_reach_the_payload_sanitized(self) -> None:
        self._create_config(
            enabled=True,
            appearance={"translations": {"de": {"title": "Hallo"}, "bad key": {"title": "nope"}}},
        )
        js = self._artifact_js()
        assert json.dumps("Hallo") in js
        assert "bad key" not in js

    def test_saving_config_schedules_artifact_sync(self) -> None:
        with patch("products.cookie_banner.backend.tasks.sync_project_cookie_banner_artifacts.delay") as mock_delay:
            with self.captureOnCommitCallbacks(execute=True):
                self._create_config(enabled=True)
            mock_delay.assert_called_once_with(self.team.id)

    def test_remote_config_no_longer_carries_the_banner(self) -> None:
        # The standalone artifact replaced siteAppsJS delivery; if the injection came
        # back, visitors would get the banner twice
        self._create_config(enabled=True)
        site_apps_js = "\n".join(RemoteConfig(team=self.team).build_config()["siteAppsJS"])
        assert "cookie-banner" not in site_apps_js


class TestSanitizeTranslations(SimpleTestCase):
    # Guards the delivery path against translation junk written outside the API
    # (widened serializer, direct DB writes): only whitelisted copy fields within
    # their length limits may reach customer sites.
    def test_invalid_entries_are_dropped(self) -> None:
        assert _sanitize_translations("not-a-dict") == {}
        assert _sanitize_translations(
            {
                "de": {"title": "Hallo", "artStyle": "hedgehog-legal", "onload": "alert(1)"},
                "not a lang": {"title": "x"},
                "fr": "not-a-dict",
                "es": {"title": "a" * 26},
                "pt-BR": {"acceptButtonText": "Aceitar", "description": 123},
            }
        ) == {
            "de": {"title": "Hallo"},
            "pt-BR": {"acceptButtonText": "Aceitar"},
        }

    def test_language_count_is_capped(self) -> None:
        raw = {f"a{chr(ord('a') + i)}": {"title": "x"} for i in range(25)}
        assert len(_sanitize_translations(raw)) == 20


class TestSanitizeCategories(SimpleTestCase):
    # Same defense-in-depth as translations: category junk written outside the API
    # must not reach customer sites, and analytics must survive any input because
    # the runtime's consent wiring depends on it.
    def test_invalid_entries_are_dropped_and_analytics_survives(self) -> None:
        assert _sanitize_categories("not-a-list") == [{"key": "analytics", "label": "Analytics"}]
        assert _sanitize_categories(
            [
                {"key": "analytics", "label": "Analytics"},
                {"key": "Bad Key", "label": "x"},
                {"key": "necessary", "label": "reserved"},
                {"key": "analytics", "label": "duplicate"},
                {"key": "chat", "label": "a" * 31},
                {"key": "ads", "label": "Ads", "description": "d" * 121},
                "not-a-dict",
                {"key": "ok", "label": "OK", "description": "Fine"},
            ]
        ) == [
            {"key": "analytics", "label": "Analytics"},
            {"key": "ads", "label": "Ads"},
            {"key": "ok", "label": "OK", "description": "Fine"},
        ]

    def test_category_count_is_capped(self) -> None:
        raw = [{"key": f"cat{i}", "label": f"Cat {i}"} for i in range(15)]
        sanitized = _sanitize_categories(raw)
        assert len(sanitized) == 10
        assert sanitized[0]["key"] == "analytics"
