import uuid
import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team
from posthog.temporal.messaging.reconcile_precalculated_data_workflow import (
    ReconcileTeamInputs,
    get_reconciliation_team_ids_activity,
    reconcile_team_precalculated_events_activity,
)

from products.cohorts.backend.models.cohort import Cohort, CohortType


def _insert_precalculated_event(
    team_id: int,
    distinct_id: str,
    person_id: uuid.UUID,
    condition: str,
    event_uuid: uuid.UUID,
    source: str,
    date: dt.date,
) -> None:
    sync_execute(
        """
        INSERT INTO precalculated_events
            (team_id, date, distinct_id, person_id, condition, uuid, source, _timestamp, _partition, _offset)
        VALUES
        """,
        [
            (
                team_id,
                date,
                distinct_id,
                str(person_id),
                condition,
                str(event_uuid),
                source,
                dt.datetime.now(dt.UTC),
                0,
                0,
            )
        ],
    )


def _insert_override(
    team_id: int,
    distinct_id: str,
    person_id: uuid.UUID,
    version: int = 1,
    timestamp: dt.datetime | None = None,
) -> None:
    # _timestamp has no column default, so it must always be set explicitly: an epoch value
    # would put the override outside the incremental lookback window.
    sync_execute(
        """
        INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version, _timestamp)
        VALUES
        """,
        [(team_id, distinct_id, str(person_id), version, timestamp or dt.datetime.now(dt.UTC))],
    )


@pytest.mark.asyncio
@pytest.mark.django_db
class TestReconcileTeamPrecalculatedEventsActivity:
    async def test_corrects_stale_rows_and_leaves_current_ones_alone(self, team):
        date = dt.date(2024, 1, 1)
        stale_uuid = uuid.uuid4()
        old_person, new_person = uuid.uuid4(), uuid.uuid4()
        synced_person = uuid.uuid4()
        unrelated_person = uuid.uuid4()

        # Stale: distinct_id was re-pointed to new_person after this row was written.
        _insert_precalculated_event(
            team.pk, "did-merged", old_person, "hash-1", stale_uuid, "cohort_event_backfill_hash-1", date
        )
        _insert_override(team.pk, "did-merged", new_person)
        # Already in sync: override agrees with the stored row.
        _insert_precalculated_event(
            team.pk, "did-synced", synced_person, "hash-1", uuid.uuid4(), "cohort_filter_hash-1", date
        )
        _insert_override(team.pk, "did-synced", synced_person)
        # No override at all: must not even be scanned, let alone corrected.
        _insert_precalculated_event(
            team.pk, "did-untouched", unrelated_person, "hash-1", uuid.uuid4(), "cohort_filter_hash-1", date
        )

        mock_producer = MagicMock()
        with patch(
            "posthog.temporal.messaging.reconcile_precalculated_data_workflow.get_producer",
            return_value=mock_producer,
        ):
            result = await ActivityEnvironment().run(
                reconcile_team_precalculated_events_activity, ReconcileTeamInputs(team_id=team.pk)
            )

        assert result.overridden_distinct_ids == 2
        assert result.rows_checked == 2
        assert result.rows_corrected == 1

        produced = [call.kwargs["data"] for call in mock_producer.produce.call_args_list]
        assert produced == [
            {
                "uuid": str(stale_uuid),
                "team_id": team.pk,
                "person_id": str(new_person),
                "distinct_id": "did-merged",
                "condition": "hash-1",
                "date": "2024-01-01",
                # The original source must survive: the backfill coordinator's
                # day-already-backfilled check filters on it.
                "source": "cohort_event_backfill_hash-1",
            }
        ]

    async def test_old_override_needs_full_scan(self, team):
        stale_uuid = uuid.uuid4()
        old_person, new_person = uuid.uuid4(), uuid.uuid4()
        _insert_precalculated_event(
            team.pk, "did-old-merge", old_person, "hash-1", stale_uuid, "cohort_filter_hash-1", dt.date(2024, 1, 1)
        )
        _insert_override(
            team.pk, "did-old-merge", new_person, timestamp=dt.datetime.now(dt.UTC) - dt.timedelta(days=10)
        )

        mock_producer = MagicMock()
        with patch(
            "posthog.temporal.messaging.reconcile_precalculated_data_workflow.get_producer",
            return_value=mock_producer,
        ):
            incremental = await ActivityEnvironment().run(
                reconcile_team_precalculated_events_activity, ReconcileTeamInputs(team_id=team.pk)
            )
            full = await ActivityEnvironment().run(
                reconcile_team_precalculated_events_activity, ReconcileTeamInputs(team_id=team.pk, full_scan=True)
            )

        # Incremental runs only react to overrides inside the lookback window; the full
        # scan is the recovery path for anything older.
        assert incremental.rows_corrected == 0
        assert full.rows_corrected == 1
        assert mock_producer.produce.call_args.kwargs["data"]["person_id"] == str(new_person)

    async def test_deleted_override_does_not_correct(self, team):
        person = uuid.uuid4()
        _insert_precalculated_event(
            team.pk, "did-deleted-override", person, "hash-1", uuid.uuid4(), "cohort_filter_hash-1", dt.date(2024, 1, 1)
        )
        sync_execute(
            """
            INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version, is_deleted, _timestamp)
            VALUES
            """,
            [(team.pk, "did-deleted-override", str(uuid.uuid4()), 2, 1, dt.datetime.now(dt.UTC))],
        )

        mock_producer = MagicMock()
        with patch(
            "posthog.temporal.messaging.reconcile_precalculated_data_workflow.get_producer",
            return_value=mock_producer,
        ):
            result = await ActivityEnvironment().run(
                reconcile_team_precalculated_events_activity, ReconcileTeamInputs(team_id=team.pk)
            )

        assert result.rows_corrected == 0
        mock_producer.produce.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.django_db
class TestGetReconciliationTeamIdsActivity:
    async def test_returns_distinct_realtime_cohort_teams_only(self, team):
        other_team = await sync_to_async(Team.objects.create)(
            organization=team.organization, project=team.project, name="other"
        )
        create_cohort = sync_to_async(Cohort.objects.create)
        await create_cohort(team=team, name="rt-1", cohort_type=CohortType.REALTIME)
        await create_cohort(team=team, name="rt-2", cohort_type=CohortType.REALTIME)
        await create_cohort(team=other_team, name="rt-deleted", cohort_type=CohortType.REALTIME, deleted=True)
        await create_cohort(team=other_team, name="batch-only")

        result = await ActivityEnvironment().run(get_reconciliation_team_ids_activity)

        assert result.team_ids == [team.pk]
