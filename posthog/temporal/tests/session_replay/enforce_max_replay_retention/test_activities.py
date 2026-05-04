import pytest
from unittest.mock import MagicMock, patch

from temporalio.testing import ActivityEnvironment

from posthog.constants import AvailableFeature
from posthog.temporal.session_replay.enforce_max_replay_retention.activities import enforce_max_replay_retention
from posthog.temporal.session_replay.enforce_max_replay_retention.types import EnforceMaxReplayRetentionInput


def _team(*, retention: str, feature_unit: str | None, feature_limit: int | None) -> MagicMock:
    organization = MagicMock()
    if feature_unit is None or feature_limit is None:
        organization.get_available_feature.return_value = None
    else:
        organization.get_available_feature.return_value = {
            "name": AvailableFeature.SESSION_REPLAY_DATA_RETENTION,
            "key": AvailableFeature.SESSION_REPLAY_DATA_RETENTION,
            "limit": feature_limit,
            "unit": feature_unit,
        }
    team = MagicMock()
    team.id = id(team)
    team.organization = organization
    team.session_recording_retention_period = retention
    return team


class _FakeQuerySet:
    def __init__(self, teams: list[MagicMock]) -> None:
        self._teams = teams

    def exclude(self, **_):
        return self

    def only(self, *_):
        return self

    def __aiter__(self):
        async def gen():
            for t in self._teams:
                yield t

        return gen()


def _patch_team_objects(teams: list[MagicMock], bulk_update: MagicMock):
    fake_qs = _FakeQuerySet(teams)
    objects = MagicMock()
    objects.exclude.return_value = fake_qs
    objects.bulk_update = bulk_update
    return patch(
        "posthog.temporal.session_replay.enforce_max_replay_retention.activities.Team.objects",
        new=objects,
    )


@pytest.mark.asyncio
async def test_reduces_retention_when_team_exceeds_entitlement():
    team = _team(retention="5y", feature_unit="year", feature_limit=1)
    bulk_update = MagicMock()

    with _patch_team_objects([team], bulk_update):
        await ActivityEnvironment().run(enforce_max_replay_retention, EnforceMaxReplayRetentionInput(dry_run=False))

    assert team.session_recording_retention_period == "1y"
    bulk_update.assert_called_once()
    args, _kwargs = bulk_update.call_args
    assert args[0] == [team]


@pytest.mark.asyncio
async def test_dry_run_does_not_persist_changes():
    team = _team(retention="5y", feature_unit="year", feature_limit=1)
    bulk_update = MagicMock()

    with _patch_team_objects([team], bulk_update):
        await ActivityEnvironment().run(enforce_max_replay_retention, EnforceMaxReplayRetentionInput(dry_run=True))

    bulk_update.assert_not_called()


@pytest.mark.asyncio
async def test_skips_team_within_entitlement():
    team = _team(retention="1y", feature_unit="year", feature_limit=5)
    bulk_update = MagicMock()

    with _patch_team_objects([team], bulk_update):
        await ActivityEnvironment().run(enforce_max_replay_retention, EnforceMaxReplayRetentionInput(dry_run=False))

    assert team.session_recording_retention_period == "1y"
    bulk_update.assert_called_once()
    args, _kwargs = bulk_update.call_args
    assert args[0] == []


@pytest.mark.asyncio
async def test_skips_team_when_org_has_no_feature():
    team = _team(retention="5y", feature_unit=None, feature_limit=None)
    bulk_update = MagicMock()

    with _patch_team_objects([team], bulk_update):
        await ActivityEnvironment().run(enforce_max_replay_retention, EnforceMaxReplayRetentionInput(dry_run=False))

    bulk_update.assert_called_once()
    args, _kwargs = bulk_update.call_args
    assert args[0] == []


@pytest.mark.asyncio
async def test_skips_team_with_invalid_current_retention():
    team = _team(retention="bogus", feature_unit="year", feature_limit=1)
    bulk_update = MagicMock()

    with _patch_team_objects([team], bulk_update):
        await ActivityEnvironment().run(enforce_max_replay_retention, EnforceMaxReplayRetentionInput(dry_run=False))

    assert team.session_recording_retention_period == "bogus"
    bulk_update.assert_called_once()
    args, _kwargs = bulk_update.call_args
    assert args[0] == []


@pytest.mark.asyncio
async def test_processes_multiple_teams_independently():
    over_entitled = _team(retention="5y", feature_unit="year", feature_limit=1)
    within_entitlement = _team(retention="90d", feature_unit="year", feature_limit=1)
    no_feature = _team(retention="5y", feature_unit=None, feature_limit=None)
    bulk_update = MagicMock()

    with _patch_team_objects([over_entitled, within_entitlement, no_feature], bulk_update):
        await ActivityEnvironment().run(enforce_max_replay_retention, EnforceMaxReplayRetentionInput(dry_run=False))

    assert over_entitled.session_recording_retention_period == "1y"
    assert within_entitlement.session_recording_retention_period == "90d"
    assert no_feature.session_recording_retention_period == "5y"
    bulk_update.assert_called_once()
    args, _kwargs = bulk_update.call_args
    assert args[0] == [over_entitled]


@pytest.mark.asyncio
async def test_handles_empty_team_set():
    bulk_update = MagicMock()

    with _patch_team_objects([], bulk_update):
        await ActivityEnvironment().run(enforce_max_replay_retention, EnforceMaxReplayRetentionInput(dry_run=False))

    bulk_update.assert_called_once()
    args, _kwargs = bulk_update.call_args
    assert args[0] == []
