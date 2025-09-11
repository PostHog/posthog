from datetime import datetime
from typing import TYPE_CHECKING

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, BaseTest

from django.core.cache import cache

from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api import router
from posthog.decorators import cached_by_filters, is_stale_filter
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team.team import Team

if TYPE_CHECKING:
    from posthog.api.routing import TeamAndOrgViewSetMixin


class DummyViewSet(*((TeamAndOrgViewSetMixin, GenericViewSet) if TYPE_CHECKING else (GenericViewSet,))):  # type: ignore
    # We don't actually want TeamAndOrgViewSetMixin's functionality in this class, but we do pretend to act like
    # TeamAndOrgViewSetMixin in terms of having `team`. To make mypy happy, we make it _think_ that the mixin is used
    team: Team

    def list(self, request):
        data = self.calculate_with_filters(request)
        return Response(data)

    @cached_by_filters
    def calculate_with_filters(self, request):
        return {"result": "bla"}


router.register(r"dummy", DummyViewSet, "dummy")


class TestCachedByFiltersDecorator(APIBaseTest):
    def setUp(self) -> None:
        DummyViewSet.team = self.team  # Simulating TeamAndOrgViewSetMixin
        cache.clear()
        super().setUp()

    def test_returns_fresh_result(self) -> None:
        response = self.client.get(f"/api/dummy").json()

        assert response["result"] == "bla"
        assert response["is_cached"] is False
        assert isinstance(response["last_refresh"], str)

    def test_returns_cached_result(self) -> None:
        # Prime the cache
        self.client.get(f"/api/dummy").json()

        response = self.client.get(f"/api/dummy").json()

        assert response["result"] == "bla"
        assert response["is_cached"] is True

    def test_team_id_from_viewset_is_used(self) -> None:
        other_team = Team.objects.create(organization=self.organization)

        # Prime the cache
        self.client.get(f"/api/dummy").json()

        # Now switch to the other team - cache should be different
        DummyViewSet.team = other_team

        response_for_other_team_initial = self.client.get(f"/api/dummy").json()
        response_for_other_team_repeated = self.client.get(f"/api/dummy").json()

        assert response_for_other_team_initial["result"] == "bla"
        assert response_for_other_team_initial["is_cached"] is False
        assert response_for_other_team_repeated["result"] == "bla"
        assert response_for_other_team_repeated["is_cached"] is True

    def test_cache_bypass_with_refresh_param(self) -> None:
        # Prime the cache
        self.client.get(f"/api/dummy").json()

        response = self.client.get(f"/api/dummy", data={"refresh": "true"}).json()

        assert response["is_cached"] is False

    def test_cache_bypass_with_invalidation_key_param(self) -> None:
        # Prime the cache
        self.client.get(f"/api/dummy").json()

        response = self.client.get(f"/api/dummy", data={"cache_invalidation_key": "abc"}).json()

        assert response["is_cached"] is False

    def test_discards_stale_response(self) -> None:
        with freeze_time("2023-02-08T12:05:23Z"):
            # Prime the cache
            self.client.get(f"/api/dummy").json()

        with freeze_time("2023-02-10T12:00:00Z"):
            # we don't need to add filters, since -7d with a
            # daily interval is the default
            response = self.client.get(f"/api/dummy").json()
            assert response["is_cached"] is False


class TestIsStaleHelper(BaseTest):
    cached_response = {
        "last_refresh": datetime.fromisoformat("2023-02-08T12:05:23+00:00"),
        "result": "bla",
    }

    def test_keeps_fresh_hourly_result(self) -> None:
        with freeze_time("2023-02-08T12:15:59Z"):
            filter = Filter(data={"interval": "hour"})

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is False

    def test_discards_stale_hourly_result(self) -> None:
        with freeze_time("2023-02-08T13:06:00Z"):
            filter = Filter(data={"interval": "hour"})

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is True

    def test_keeps_fresh_daily_result(self) -> None:
        with freeze_time("2023-02-08T13:59:59Z"):
            filter = Filter(data={"interval": "day"})

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is False

    def test_discards_stale_daily_result(self) -> None:
        with freeze_time("2023-02-09T00:00:00Z"):
            filter = Filter(data={"interval": "day"})

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is True

    def test_keeps_fresh_weekly_result(self) -> None:
        with freeze_time("2023-02-09T00:04:59Z"):
            filter = Filter(data={"interval": "week"})

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is False

    def test_discards_stale_weekly_result(self) -> None:
        with freeze_time("2023-02-12T00:00:00Z"):
            filter = Filter(data={"interval": "week"})

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is True

    def test_keeps_fresh_monthly_result(self) -> None:
        with freeze_time("2023-02-08T12:04:59Z"):
            filter = Filter(data={"interval": "month"})

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is False

    def test_discards_stale_monthly_result(self) -> None:
        with freeze_time("2023-03-01T00:00:00Z"):
            filter = Filter(data={"interval": "month"})

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is True

    def test_keeps_fresh_result_from_fixed_range(self) -> None:
        filter = Filter(data={"interval": "day", "date_from": "2000-01-01", "date_to": "2000-01-10"})

        stale = is_stale_filter(self.team, filter, self.cached_response)

        assert stale is False

    def test_keeps_fresh_result_with_date_to_in_future(self) -> None:
        with freeze_time("2023-02-08T12:15:59Z"):
            filter = Filter(data={"interval": "day", "date_to": "2999-01-01"})

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is False

    def test_keeps_fresh_stickiness_result(self) -> None:
        with freeze_time("2023-02-08T12:15:59Z"):
            filter = StickinessFilter(data={}, team=self.team)

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is False

    def test_discards_stale_stickiness_result(self) -> None:
        with freeze_time("2023-02-09T00:00:00Z"):
            filter = StickinessFilter(data={}, team=self.team)

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is True

    def test_keeps_fresh_path_result(self) -> None:
        with freeze_time("2023-02-08T12:15:59Z"):
            filter = PathFilter()

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is False

    def test_discards_stale_path_result(self) -> None:
        with freeze_time("2023-02-09T00:00:00Z"):
            filter = PathFilter()

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is True

    def test_keeps_fresh_retention_hourly_result(self) -> None:
        with freeze_time("2023-02-08T12:15:59Z"):
            filter = RetentionFilter(data={"period": "Hour"})

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is False

    def test_discards_stale_retention_hourly_result(self) -> None:
        with freeze_time("2023-02-08T13:06:00Z"):
            filter = RetentionFilter(data={"period": "Hour"})

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is True

    def test_keeps_fresh_retention_result(self) -> None:
        with freeze_time("2023-02-08T12:15:59Z"):
            filter = RetentionFilter()

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is False

    def test_discards_stale_retention_result(self) -> None:
        with freeze_time("2023-02-09T00:00:00Z"):
            filter = RetentionFilter()

            stale = is_stale_filter(self.team, filter, self.cached_response)

            assert stale is True
