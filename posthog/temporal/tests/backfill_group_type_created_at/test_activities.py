from datetime import UTC, datetime

import pytest
from posthog.test.base import _create_event, flush_persons_and_events
from unittest.mock import patch

from asgiref.sync import sync_to_async

from posthog.models import Team
from posthog.persons_db import persons_db_connection
from posthog.temporal.backfill_group_type_created_at.activities import (
    _build_backfill_plan,
    apply_group_type_created_at_backfill,
    plan_group_type_created_at_backfill,
)
from posthog.temporal.backfill_group_type_created_at.types import (
    ApplyBackfillInput,
    BackfillGroupTypeCreatedAtError,
    GroupTypeUpdate,
    PlanBackfillInput,
)
from posthog.test.persons import create_group_type_mapping
from posthog.test.test_utils import create_group_type_mapping_without_created_at

pytestmark = pytest.mark.persons_db_direct

CREATED_AT = datetime(2026, 5, 31, 22, 33, tzinfo=UTC)
EARLIER = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 6, 6, 0, 0, tzinfo=UTC)


def _mapping(index: int, created_at: datetime | None) -> dict:
    return {"group_type": f"g{index}", "group_type_index": index, "created_at": created_at}


def test_build_plan_lowers_created_at_to_earliest_event():
    updates, skipped = _build_backfill_plan([_mapping(0, CREATED_AT)], {0: EARLIER})

    assert skipped == []
    assert updates == [
        {
            "group_type": "g0",
            "group_type_index": 0,
            "current_created_at": CREATED_AT.isoformat(),
            "new_created_at": EARLIER.isoformat(),
        }
    ]


@pytest.mark.parametrize(
    "created_at,earliest,expected_reason",
    [
        (None, {0: EARLIER}, "created_at already null"),
        (CREATED_AT, {}, "no events carry this group"),
        (CREATED_AT, {0: LATER}, "created_at already at or before earliest event"),
        (CREATED_AT, {0: CREATED_AT}, "created_at already at or before earliest event"),
    ],
)
def test_build_plan_skips_when_no_correction_needed(created_at, earliest, expected_reason):
    updates, skipped = _build_backfill_plan([_mapping(0, created_at)], earliest)

    assert updates == []
    assert len(skipped) == 1
    assert skipped[0]["reason"] == expected_reason


def test_build_plan_handles_mixed_mappings():
    mappings = [_mapping(0, CREATED_AT), _mapping(1, None), _mapping(2, CREATED_AT)]
    earliest = {0: EARLIER, 2: LATER}

    updates, skipped = _build_backfill_plan(mappings, earliest)

    assert [u["group_type_index"] for u in updates] == [0]
    assert {s["group_type_index"] for s in skipped} == {1, 2}


# Integration tests below exercise the real activities against Postgres + ClickHouse.

MAPPING_CREATED_AT = datetime(2026, 5, 31, 22, 33, tzinfo=UTC)


def _seed_mapping(team: Team, index: int, group_type: str, created_at: datetime | None) -> None:
    if created_at is None:
        create_group_type_mapping_without_created_at(
            team=team, project_id=team.project_id, group_type=group_type, group_type_index=index
        )
    else:
        create_group_type_mapping(
            team=team,
            project_id=team.project_id,
            group_type=group_type,
            group_type_index=index,
            created_at=created_at,
        )


def _seed_event(team: Team, distinct_id: str, group_index: int, group_key: str, timestamp: str) -> None:
    # Setting properties[$group_N] populates the materialized $group_N column on the events table.
    _create_event(
        team=team,
        event="$pageview",
        distinct_id=distinct_id,
        timestamp=timestamp,
        properties={f"$group_{group_index}": group_key},
    )


def _read_created_at(project_id: int, index: int) -> datetime | None:
    with persons_db_connection(writer=True) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT created_at FROM posthog_grouptypemapping WHERE project_id = %s AND group_type_index = %s",
            (project_id, index),
        )
        row = cursor.fetchone()
        return row[0] if row else None


@pytest.mark.django_db(transaction=True)
class TestPlanGroupTypeCreatedAtBackfillIntegration:
    @pytest.fixture(autouse=True)
    def setup(self, team, activity_environment):
        self.team = team
        self.activity_environment = activity_environment
        yield

    @pytest.mark.asyncio
    async def test_lowers_created_at_to_earliest_event(self):
        @sync_to_async
        def seed():
            _seed_mapping(self.team, 0, "organization", MAPPING_CREATED_AT)
            _seed_event(self.team, "u1", 0, "acme", "2023-03-01T00:00:00Z")
            _seed_event(self.team, "u2", 0, "acme", "2023-01-15T10:00:00Z")
            flush_persons_and_events()

        await seed()

        result = await self.activity_environment.run(
            plan_group_type_created_at_backfill, PlanBackfillInput(team_id=self.team.id)
        )

        assert result["project_id"] == self.team.project_id
        assert result["skipped"] == []
        assert len(result["updates"]) == 1
        update = result["updates"][0]
        assert update["group_type_index"] == 0
        assert update["group_type"] == "organization"
        assert datetime.fromisoformat(update["new_created_at"]) == datetime(2023, 1, 15, 10, 0, 0, tzinfo=UTC)
        assert datetime.fromisoformat(update["current_created_at"]) == MAPPING_CREATED_AT

    @pytest.mark.asyncio
    async def test_skips_mapping_with_null_created_at(self):
        @sync_to_async
        def seed():
            _seed_mapping(self.team, 0, "organization", None)
            _seed_event(self.team, "u1", 0, "acme", "2023-01-15T10:00:00Z")
            flush_persons_and_events()

        await seed()

        result = await self.activity_environment.run(
            plan_group_type_created_at_backfill, PlanBackfillInput(team_id=self.team.id)
        )

        assert result["updates"] == []
        assert any(s["reason"] == "created_at already null" for s in result["skipped"])

    @pytest.mark.asyncio
    async def test_skips_when_no_events_carry_the_group(self):
        @sync_to_async
        def seed():
            _seed_mapping(self.team, 0, "organization", MAPPING_CREATED_AT)
            # Event carries a different group index, so $group_0 stays empty.
            _seed_event(self.team, "u1", 1, "acme", "2023-01-15T10:00:00Z")
            flush_persons_and_events()

        await seed()

        result = await self.activity_environment.run(
            plan_group_type_created_at_backfill, PlanBackfillInput(team_id=self.team.id)
        )

        assert result["updates"] == []
        assert any(s["reason"] == "no events carry this group" for s in result["skipped"])

    @pytest.mark.asyncio
    async def test_skips_when_created_at_already_early(self):
        @sync_to_async
        def seed():
            _seed_mapping(self.team, 0, "organization", datetime(2020, 1, 1, tzinfo=UTC))
            _seed_event(self.team, "u1", 0, "acme", "2023-01-15T10:00:00Z")
            flush_persons_and_events()

        await seed()

        result = await self.activity_environment.run(
            plan_group_type_created_at_backfill, PlanBackfillInput(team_id=self.team.id)
        )

        assert result["updates"] == []
        assert any(s["reason"] == "created_at already at or before earliest event" for s in result["skipped"])

    @pytest.mark.asyncio
    async def test_raises_for_invalid_team(self):
        with pytest.raises(BackfillGroupTypeCreatedAtError, match="Team 99999999 not found"):
            await self.activity_environment.run(
                plan_group_type_created_at_backfill, PlanBackfillInput(team_id=99999999)
            )

    @pytest.mark.asyncio
    async def test_considers_events_across_all_environments_in_project(self):
        @sync_to_async
        def seed():
            _seed_mapping(self.team, 0, "organization", MAPPING_CREATED_AT)
            env_b = Team.objects.create(organization=self.team.organization, project=self.team.project, name="env-b")
            # The earliest event lives in a sibling environment of the same project.
            _seed_event(self.team, "u1", 0, "acme", "2023-03-01T00:00:00Z")
            _seed_event(env_b, "u2", 0, "acme", "2023-01-01T00:00:00Z")
            flush_persons_and_events()
            return env_b.id

        env_b_id = await seed()

        result = await self.activity_environment.run(
            plan_group_type_created_at_backfill, PlanBackfillInput(team_id=self.team.id)
        )

        assert env_b_id in result["team_ids_in_project"]
        assert len(result["updates"]) == 1
        assert datetime.fromisoformat(result["updates"][0]["new_created_at"]) == datetime(2023, 1, 1, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_ignores_events_from_other_projects(self, organization):
        @sync_to_async
        def seed():
            _seed_mapping(self.team, 0, "organization", MAPPING_CREATED_AT)
            other_project_team = Team.objects.create(organization=organization, name="other-project")
            # A much earlier event exists, but under a team in a DIFFERENT project.
            _seed_event(self.team, "u1", 0, "acme", "2023-03-01T00:00:00Z")
            _seed_event(other_project_team, "u2", 0, "acme", "2020-01-01T00:00:00Z")
            flush_persons_and_events()
            return other_project_team.id

        other_team_id = await seed()

        result = await self.activity_environment.run(
            plan_group_type_created_at_backfill, PlanBackfillInput(team_id=self.team.id)
        )

        assert other_team_id not in result["team_ids_in_project"]
        assert len(result["updates"]) == 1
        # The other project's 2020 event must not pull this project's created_at back.
        assert datetime.fromisoformat(result["updates"][0]["new_created_at"]) == datetime(2023, 3, 1, tzinfo=UTC)


@pytest.mark.django_db(transaction=True)
class TestApplyGroupTypeCreatedAtBackfillIntegration:
    @pytest.fixture(autouse=True)
    def setup(self, team, activity_environment):
        self.team = team
        self.activity_environment = activity_environment
        yield

    def _update(self, index: int, new_created_at: datetime) -> GroupTypeUpdate:
        return {
            "group_type": "organization",
            "group_type_index": index,
            "current_created_at": MAPPING_CREATED_AT.isoformat(),
            "new_created_at": new_created_at.isoformat(),
        }

    @pytest.mark.asyncio
    async def test_lowers_created_at(self):
        target = datetime(2023, 1, 15, 10, 0, 0, tzinfo=UTC)

        @sync_to_async
        def seed():
            _seed_mapping(self.team, 0, "organization", MAPPING_CREATED_AT)

        await seed()

        result = await self.activity_environment.run(
            apply_group_type_created_at_backfill,
            ApplyBackfillInput(project_id=self.team.project_id, updates=[self._update(0, target)]),
        )

        assert result["updated"] == 1
        assert await sync_to_async(_read_created_at)(self.team.project_id, 0) == target

    @pytest.mark.asyncio
    async def test_does_not_raise_created_at(self):
        # The created_at__gt guard must make this a no-op: the stored value is already earlier.
        already_early = datetime(2020, 1, 1, tzinfo=UTC)

        @sync_to_async
        def seed():
            _seed_mapping(self.team, 0, "organization", already_early)

        await seed()

        result = await self.activity_environment.run(
            apply_group_type_created_at_backfill,
            ApplyBackfillInput(
                project_id=self.team.project_id, updates=[self._update(0, datetime(2023, 1, 1, tzinfo=UTC))]
            ),
        )

        assert result["updated"] == 0
        assert await sync_to_async(_read_created_at)(self.team.project_id, 0) == already_early

    @pytest.mark.asyncio
    async def test_only_updates_target_project(self, organization):
        target = datetime(2023, 1, 1, tzinfo=UTC)

        @sync_to_async
        def seed():
            _seed_mapping(self.team, 0, "organization", MAPPING_CREATED_AT)
            other_team = Team.objects.create(organization=organization, name="other-project")
            create_group_type_mapping(
                team=other_team,
                project_id=other_team.project_id,
                group_type="organization",
                group_type_index=0,
                created_at=MAPPING_CREATED_AT,
            )
            return other_team.project_id

        other_project_id = await seed()

        await self.activity_environment.run(
            apply_group_type_created_at_backfill,
            ApplyBackfillInput(project_id=self.team.project_id, updates=[self._update(0, target)]),
        )

        assert await sync_to_async(_read_created_at)(self.team.project_id, 0) == target
        # The other project's mapping must be untouched.
        assert await sync_to_async(_read_created_at)(other_project_id, 0) == MAPPING_CREATED_AT

    @pytest.mark.asyncio
    async def test_invalidates_group_types_cache(self):
        @sync_to_async
        def seed():
            _seed_mapping(self.team, 0, "organization", MAPPING_CREATED_AT)

        await seed()

        with patch(
            "posthog.temporal.backfill_group_type_created_at.activities.invalidate_group_types_cache"
        ) as mock_invalidate:
            await self.activity_environment.run(
                apply_group_type_created_at_backfill,
                ApplyBackfillInput(
                    project_id=self.team.project_id, updates=[self._update(0, datetime(2023, 1, 1, tzinfo=UTC))]
                ),
            )

        mock_invalidate.assert_called_once_with(self.team.project_id)
