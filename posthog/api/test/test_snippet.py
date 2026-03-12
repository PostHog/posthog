import json

from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.test import override_settings

from rest_framework import status

import posthog.models.snippet_versioning as sv
from posthog.models.snippet_versioning import REDIS_POINTER_MAP_KEY


class TestSnippetResolveAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        sv._pointer_map_cache = None
        sv._pointer_map_cache_time = 0
        pointers = {"1": "1.359.0", "1.358": "1.358.0", "1.359": "1.359.0"}
        cache.set(REDIS_POINTER_MAP_KEY, json.dumps(pointers))

    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)
        sv._pointer_map_cache = None
        sv._pointer_map_cache_time = 0
        super().tearDown()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_resolve_requires_pin_param(self):
        response = self.client.get(f"/api/projects/{self.team.id}/snippet/resolve/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "pin query parameter is required"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_resolve_with_exact_pin(self):
        response = self.client.get(f"/api/projects/{self.team.id}/snippet/resolve/?pin=1.358.0")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["resolved"] == "1.358.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_resolve_with_unknown_exact_version(self):
        response = self.client.get(f"/api/projects/{self.team.id}/snippet/resolve/?pin=99.99.99")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_resolve_with_major_pin(self):
        response = self.client.get(f"/api/projects/{self.team.id}/snippet/resolve/?pin=1")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["resolved"] == "1.359.0"


class TestSnippetVersionAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        sv._pointer_map_cache = None
        sv._pointer_map_cache_time = 0
        pointers = {"1": "1.359.0", "1.358": "1.358.0", "1.359": "1.359.0"}
        cache.set(REDIS_POINTER_MAP_KEY, json.dumps(pointers))

    def tearDown(self):
        cache.delete(REDIS_POINTER_MAP_KEY)
        sv._pointer_map_cache = None
        sv._pointer_map_cache_time = 0
        super().tearDown()

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_get_version_returns_current_state(self):
        response = self.client.get(f"/api/projects/{self.team.id}/snippet/version/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["snippet_version_pin"] is None
        assert data["resolved_version"] == "1.359.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_patch_version_updates_pin(self):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/snippet/version/",
            {"snippet_version_pin": "1.358.0"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["snippet_version_pin"] == "1.358.0"
        assert data["resolved_version"] == "1.358.0"

    @override_settings(POSTHOG_JS_S3_BUCKET="test-bucket")
    def test_patch_unknown_version_rejected(self):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/snippet/version/",
            {"snippet_version_pin": "99.99.99"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
