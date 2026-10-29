import uuid
from typing import Any

from posthog.test.base import BaseTest

from django.apps import apps
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.api.team.team_serializer import TeamSerializer
from posthog.caching.organization_serializer_cache import _bump_org_serializer_cache_version
from posthog.caching.team_serializer_cache import (
    PER_REQUEST_FIELDS,
    _team_cache_version,
    bump_team_cache_version,
    cached_team_app_context,
)
from posthog.models import Team
from posthog.models.team.extensions import get_or_create_team_extension

LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class FakeTeamSerializer:
    def __init__(self, label: str) -> None:
        self.label = label
        self.builds = 0

    @property
    def data(self) -> dict[str, Any]:
        self.builds += 1
        return {"name": self.label, **dict.fromkeys(PER_REQUEST_FIELDS, f"{self.label} build {self.builds}")}

    def __getattr__(self, name: str) -> Any:
        if name.startswith("get_"):
            return lambda team: f"{self.label} fresh {name}"
        raise AttributeError(name)


@override_settings(CACHES=LOCMEM_CACHE)
class TestCachedTeamAppContext(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        self.team = Team(id=1, organization_id=uuid.uuid4(), ingested_event=True)

    def test_reuses_the_entry_and_refreshes_per_request_fields(self):
        first = FakeTeamSerializer("first")
        second = FakeTeamSerializer("second")

        cached_team_app_context(first, self.team, user_id=1)
        actual = cached_team_app_context(second, self.team, user_id=1)

        assert second.builds == 0
        assert actual["name"] == "first"
        assert {field: actual[field] for field in PER_REQUEST_FIELDS} == {
            field: f"second fresh get_{field}" for field in PER_REQUEST_FIELDS
        }

    @parameterized.expand(
        [
            ("another_user", lambda team: None, 2),
            ("team_version_bump", lambda team: bump_team_cache_version(team.pk), 1),
            ("org_version_bump", lambda team: _bump_org_serializer_cache_version(str(team.organization_id)), 1),
        ]
    )
    def test_rebuilds_for(self, _name, change, second_user_id):
        cached_team_app_context(FakeTeamSerializer("first"), self.team, user_id=1)
        change(self.team)
        second = FakeTeamSerializer("second")

        actual = cached_team_app_context(second, self.team, user_id=second_user_id)

        assert second.builds == 1
        assert actual["name"] == "second"

    def test_the_team_serializer_builds_every_per_request_field(self):
        assert [field for field in PER_REQUEST_FIELDS if not hasattr(TeamSerializer, f"get_{field}")] == []

    def test_never_caches_a_team_without_events(self):
        # Ingestion sets ingested_event with raw SQL, so no signal would clear the entry.
        self.team.ingested_event = False
        cached_team_app_context(FakeTeamSerializer("first"), self.team, user_id=1)
        second = FakeTeamSerializer("second")

        cached_team_app_context(second, self.team, user_id=1)

        assert second.builds == 1


class TestTeamCacheInvalidation(BaseTest):
    @parameterized.expand(
        [
            ("team", lambda team: team.save()),
            ("revenue_analytics_config", lambda team: team.revenue_analytics_config.save()),
            ("marketing_analytics_config", lambda team: team.marketing_analytics_config.save()),
            ("customer_analytics_config", lambda team: team.customer_analytics_config.save()),
            ("workflows_config", lambda team: team.workflows_config.save()),
            ("feature_flag_policy_config", lambda team: team.feature_flag_policy_config.save()),
            (
                "managed_viewset",
                lambda team: (
                    apps.get_model("data_modeling", "DataWarehouseManagedViewSet")
                    .objects.get_or_create(team=team, kind="revenue_analytics")[0]
                    .save()
                ),
            ),
            (
                "heatmap_config",
                lambda team: get_or_create_team_extension(team, apps.get_model("posthog", "TeamHeatmapConfig")).save(),
            ),
            (
                "home_tab_dashboard_config",
                lambda team: get_or_create_team_extension(
                    team, apps.get_model("dashboards", "TeamHomeTabDashboardConfig")
                ).save(),
            ),
        ]
    )
    def test_a_write_bumps_the_team_version(self, _name, write):
        with self.captureOnCommitCallbacks(execute=True):
            write(self.team)
        before = _team_cache_version(self.team.pk)

        with self.captureOnCommitCallbacks(execute=True):
            write(self.team)

        assert _team_cache_version(self.team.pk) > before
