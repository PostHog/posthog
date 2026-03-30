import json

from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.test import override_settings

from rest_framework import status

import posthog.models.js_snippet_versioning as sv
from posthog.models.js_snippet_versioning import REDIS_POINTER_MAP_KEY


def _make_manifest(versions: list[str], pointers: dict[str, str]) -> dict:
    return {"versions": versions, "pointers": pointers}


def _reset_caches():
    sv._cached_manifest = None


MANIFEST = _make_manifest(
    versions=["1.358.0", "1.359.0"],
    pointers={"1": "1.359.0", "1.358": "1.358.0", "1.359": "1.359.0"},
)


class TestJsSnippetResolveAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        _reset_caches()
        cache.set(REDIS_POINTER_MAP_KEY, json.dumps(MANIFEST))

    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)
        _reset_caches()
        super().tearDown()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_resolve_requires_pin_param(self):
        response = self.client.get(f"/api/projects/{self.team.id}/js-snippet/resolve/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "pin query parameter is required"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_resolve_with_exact_pin(self):
        response = self.client.get(f"/api/projects/{self.team.id}/js-snippet/resolve/?pin=1.358.0")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["resolved"] == "1.358.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_resolve_with_unknown_exact_version(self):
        response = self.client.get(f"/api/projects/{self.team.id}/js-snippet/resolve/?pin=99.99.99")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_resolve_with_minor_pin(self):
        response = self.client.get(f"/api/projects/{self.team.id}/js-snippet/resolve/?pin=1.358")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["resolved"] == "1.358.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_resolve_with_major_pin(self):
        response = self.client.get(f"/api/projects/{self.team.id}/js-snippet/resolve/?pin=1")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["resolved"] == "1.359.0"


class TestJsSnippetVersionAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        _reset_caches()
        cache.set(REDIS_POINTER_MAP_KEY, json.dumps(MANIFEST))

    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)
        _reset_caches()
        super().tearDown()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_get_version_returns_current_state(self):
        response = self.client.get(f"/api/projects/{self.team.id}/js-snippet/version/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["requested_version"] is None
        assert data["resolved_version"] == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_patch_version_updates_pin(self):
        from posthog.models.team.js_snippet_config import TeamJsSnippetConfig

        response = self.client.patch(
            f"/api/projects/{self.team.id}/js-snippet/version/",
            {"js_snippet_version": "1.358.0"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["requested_version"] == "1.358.0"
        assert data["resolved_version"] == "1.358.0"

        db_config = TeamJsSnippetConfig.objects.get(team=self.team)
        assert db_config.js_snippet_version == "1.358.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_patch_empty_string_clears_pin(self):
        self.client.patch(
            f"/api/projects/{self.team.id}/js-snippet/version/",
            {"js_snippet_version": "1.358.0"},
            content_type="application/json",
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/js-snippet/version/",
            {"js_snippet_version": ""},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["requested_version"] is None
        assert data["resolved_version"] == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_patch_null_clears_pin(self):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/js-snippet/version/",
            {"js_snippet_version": None},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["requested_version"] is None
        assert data["resolved_version"] == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_patch_unknown_version_rejected(self):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/js-snippet/version/",
            {"js_snippet_version": "99.99.99"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_unauthenticated_access_rejected(self):
        self.client.logout()
        response = self.client.get(f"/api/projects/{self.team.id}/js-snippet/version/")
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
