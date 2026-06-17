import pytest
from unittest.mock import MagicMock, patch

from temporalio.testing import ActivityEnvironment

from posthog.constants import AvailableFeature
from posthog.temporal.sync_events_retention.activities import sync_events_retention
from posthog.temporal.sync_events_retention.types import SyncEventsRetentionInput


def _team(*, current_months: int, feature_unit: str | None, feature_limit: int | None) -> MagicMock:
    organization = MagicMock()
    if feature_unit is None or feature_limit is None:
        organization.get_available_feature.return_value = None
    else:
        organization.get_available_feature.return_value = {
            "name": AvailableFeature.PRODUCT_ANALYTICS_DATA_RETENTION,
            "key": AvailableFeature.PRODUCT_ANALYTICS_DATA_RETENTION,
            "limit": feature_limit,
            "unit": feature_unit,
        }
    team = MagicMock()
    team.id = id(team)
    team.organization = organization
    team.event_retention_months = current_months
    return team


class _FakeQuerySet:
    def __init__(self, teams: list[MagicMock]) -> None:
        self._teams = teams

    def select_related(self, *_):
        return self

    def only(self, *_):
        return self

    def __aiter__(self):
        async def gen():
            for t in self._teams:
                yield t

        return gen()


def _patch_team_objects(teams: list[MagicMock], bulk_update: MagicMock):
    objects = MagicMock()
    objects.select_related.return_value = _FakeQuerySet(teams)
    objects.bulk_update = bulk_update
    return patch(
        "posthog.temporal.sync_events_retention.activities.Team.objects",
        new=objects,
    )


@pytest.mark.asyncio
async def test_sets_months_from_entitlement():
    team = _team(current_months=84, feature_unit="year", feature_limit=1)
    bulk_update = MagicMock()

    with _patch_team_objects([team], bulk_update):
        await ActivityEnvironment().run(sync_events_retention, SyncEventsRetentionInput(dry_run=False))

    assert team.event_retention_months == 12
    bulk_update.assert_called_once()
    assert bulk_update.call_args[0][0] == [team]
    # Guard the billing key: the sync must read the entitlement billing actually emits.
    team.organization.get_available_feature.assert_called_with(AvailableFeature.PRODUCT_ANALYTICS_DATA_RETENTION)


@pytest.mark.asyncio
async def test_defaults_to_seven_years_without_entitlement():
    # No billing entitlement → grandfather to 7 years (84 months) rather than reducing.
    team = _team(current_months=12, feature_unit=None, feature_limit=None)
    bulk_update = MagicMock()

    with _patch_team_objects([team], bulk_update):
        await ActivityEnvironment().run(sync_events_retention, SyncEventsRetentionInput(dry_run=False))

    assert team.event_retention_months == 84
    assert bulk_update.call_args[0][0] == [team]


@pytest.mark.asyncio
async def test_skips_team_already_at_target():
    team = _team(current_months=84, feature_unit=None, feature_limit=None)
    bulk_update = MagicMock()

    with _patch_team_objects([team], bulk_update):
        await ActivityEnvironment().run(sync_events_retention, SyncEventsRetentionInput(dry_run=False))

    assert team.event_retention_months == 84
    assert bulk_update.call_args[0][0] == []


@pytest.mark.asyncio
async def test_dry_run_does_not_persist():
    team = _team(current_months=84, feature_unit="year", feature_limit=1)
    bulk_update = MagicMock()

    with _patch_team_objects([team], bulk_update):
        await ActivityEnvironment().run(sync_events_retention, SyncEventsRetentionInput(dry_run=True))

    bulk_update.assert_not_called()
