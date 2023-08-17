from posthog.decorators import cached_by_filters

from django.core.cache import cache

from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet
from rest_framework.response import Response

from posthog.test.base import APIBaseTest
from posthog.api import router

factory = APIRequestFactory()


class DummyViewSet(GenericViewSet):
    def list(self, request):
        data = self.calculate_with_filters(request)
        return Response(data)

    @cached_by_filters
    def calculate_with_filters(self, request):
        return {"result": "bla"}


class TestDecorators(APIBaseTest):
    def setUp(self) -> None:
        cache.clear()

        router.register(r"dummy", DummyViewSet, "dummy")

        super().setUp()

    def test_returns_fresh_result(self) -> None:
        response = self.client.get(f"/api/dummy").json()

        assert response["result"] == "bla"
        assert response["is_cached"] is False
        assert isinstance(response["last_refresh"], str)

    def test_returns_cached_result(self) -> None:
        # cache the result
        self.client.get(f"/api/dummy").json()

        response = self.client.get(f"/api/dummy").json()

        assert response["result"] == "bla"
        assert response["is_cached"] is True

    def test_cache_bypass_with_refresh_param(self) -> None:
        # cache the result
        self.client.get(f"/api/dummy").json()

        response = self.client.get(f"/api/dummy", data={"refresh": "true"}).json()

        assert response["is_cached"] is False

    def test_cache_bypass_with_invalidation_key_param(self) -> None:
        # cache the result
        self.client.get(f"/api/dummy").json()

        response = self.client.get(f"/api/dummy", data={"cache_invalidation_key": "abc"}).json()

        assert response["is_cached"] is False
