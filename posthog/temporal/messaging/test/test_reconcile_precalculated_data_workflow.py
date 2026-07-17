import uuid
import datetime as dt

import pytest
from unittest.mock import MagicMock, Mock, patch

from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team
from posthog.temporal.messaging.reconcile_precalculated_data_workflow import (
    ReconcileTeamInputs,
    _extract_person_property_filters,
    _get_realtime_person_property_filters,
    _positive_int_env,
    get_reconciliation_run_config_activity,
    get_reconciliation_team_ids_activity,
    reconcile_team_precalculated_events_activity,
    reconcile_team_precalculated_person_properties_activity,
)
from posthog.test.persons import create_person

from products.cohorts.backend.models.cohort import Cohort, CohortType


def _is_set_bytecode(property_key: str) -> list:
    # person.properties.<key> != NULL — the same is_set bytecode pattern used in
    # test_backfill_precalculated_person_properties_workflow.py's filter-evaluation tests.
    return ["_H", 1, 31, 32, property_key, 32, "properties", 32, "person", 1, 3, 12]


class TestPositiveIntEnv:
    @parameterized.expand(
        [
            ("valid", "500", 500),
            ("malformed", "not-a-number", 1000),
            ("zero", "0", 1000),
            ("negative", "-5", 1000),
        ]
    )
    def test_parses_or_falls_back_to_default(self, _name, env_value, expected):
        # Guards the reconciliation activity's batch-size/lookback knobs: a zero batch size
        # breaks range()'s step, and a zero/negative lookback silently excludes every override.
        with patch.dict("os.environ", {"RECONCILE_TEST_VAR": env_value}):
            assert _positive_int_env("RECONCILE_TEST_VAR", 1000, MagicMock()) == expected

    def test_unset_uses_default(self, monkeypatch):
        monkeypatch.delenv("RECONCILE_TEST_VAR", raising=False)
        assert _positive_int_env("RECONCILE_TEST_VAR", 1000, MagicMock()) == 1000


class TestGetReconciliationRunConfigActivity:
    @pytest.mark.asyncio
    async def test_defaults_when_env_unset(self, monkeypatch):
        # The workflow shares this config across every team in a run; a regression here
        # (e.g. reading env vars per-team instead) would silently reopen the queueing bug
        # this activity exists to fix.
        monkeypatch.delenv("RECONCILE_EVENTS_OVERRIDES_LOOKBACK_HOURS", raising=False)
        monkeypatch.delenv("RECONCILE_EVENTS_TEAM_CONCURRENCY", raising=False)

        before = dt.datetime.now(dt.UTC)
        result = await ActivityEnvironment().run(get_reconciliation_run_config_activity)
        after = dt.datetime.now(dt.UTC)

        assert result.team_concurrency == 5
        assert before - dt.timedelta(hours=48) <= result.since <= after - dt.timedelta(hours=48)


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
@pytest.mark.django_db(transaction=True)
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


class TestExtractPersonPropertyFilters:
    def test_no_filters_returns_empty(self):
        cohort = Mock(filters=None)
        assert _extract_person_property_filters(cohort) == []

    def test_traverses_and_or_groups(self):
        cohort = Mock(
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "type": "person",
                                    "key": "$browser",
                                    "conditionHash": "hash-1",
                                    "bytecode": _is_set_bytecode("$browser"),
                                }
                            ],
                        }
                    ],
                }
            }
        )

        result = _extract_person_property_filters(cohort)

        assert [f.condition_hash for f in result] == ["hash-1"]

    def test_leaf_missing_bytecode_is_skipped(self):
        # A leaf without conditionHash/bytecode/key can't be evaluated later — skipping it
        # here (rather than raising) avoids failing reconciliation for every other condition.
        cohort = Mock(
            filters={
                "properties": {
                    "type": "person",
                    "key": "$browser",
                    "conditionHash": "hash-1",
                    # no bytecode
                }
            }
        )
        assert _extract_person_property_filters(cohort) == []


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestGetRealtimePersonPropertyFilters:
    async def test_dedupes_condition_shared_across_cohorts(self, team):
        # Two realtime cohorts using the same condition_hash must produce one filter entry
        # (not two) — reconciliation would otherwise evaluate and emit for it twice per batch.
        bytecode = _is_set_bytecode("$browser")
        create_cohort = sync_to_async(Cohort.objects.create)
        cohort_a = await create_cohort(
            team=team,
            name="rt-a",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "person",
                    "key": "$browser",
                    "conditionHash": "shared-hash",
                    "bytecode": bytecode,
                }
            },
        )
        cohort_b = await create_cohort(
            team=team,
            name="rt-b",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "person",
                    "key": "$browser",
                    "conditionHash": "shared-hash",
                    "bytecode": bytecode,
                }
            },
        )

        result = await _get_realtime_person_property_filters(team.pk)

        assert len(result) == 1
        assert result[0].condition_hash == "shared-hash"
        assert sorted(result[0].cohort_ids) == sorted([cohort_a.pk, cohort_b.pk])


def _insert_person_properties_verdict(
    team_id: int,
    distinct_id: str,
    person_id: uuid.UUID,
    condition: str,
    matches: bool,
    timestamp: dt.datetime | None = None,
) -> None:
    sync_execute(
        """
        INSERT INTO precalculated_person_properties
            (team_id, distinct_id, person_id, condition, matches, source, _timestamp, _offset)
        VALUES
        """,
        [
            (
                team_id,
                distinct_id,
                str(person_id),
                condition,
                matches,
                f"cohort_filter_{condition}",
                timestamp or dt.datetime.now(dt.UTC),
                0,
            )
        ],
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestReconcileTeamPrecalculatedPersonPropertiesActivity:
    async def test_corrects_verdict_and_attribution_after_merge(self, team):
        # Old person never had $browser set; the surviving person does. A merge must both
        # re-attribute the row to the surviving person_id and flip the stale matches=False
        # verdict to True — leaving either uncorrected is the bug this activity fixes.
        condition_hash = "browser-set"
        await sync_to_async(Cohort.objects.create)(
            team=team,
            name="rt-browser",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "person",
                    "key": "$browser",
                    "conditionHash": condition_hash,
                    "bytecode": _is_set_bytecode("$browser"),
                }
            },
        )

        old_person = await sync_to_async(create_person)(team=team, distinct_ids=[], properties={})
        new_person = await sync_to_async(create_person)(
            team=team, distinct_ids=["did-merged"], properties={"$browser": "Chrome"}
        )
        _insert_person_properties_verdict(team.pk, "did-merged", old_person.uuid, condition_hash, matches=False)
        _insert_override(team.pk, "did-merged", new_person.uuid)

        mock_producer = MagicMock()
        with patch(
            "posthog.temporal.messaging.reconcile_precalculated_data_workflow.get_producer",
            return_value=mock_producer,
        ):
            result = await ActivityEnvironment().run(
                reconcile_team_precalculated_person_properties_activity, ReconcileTeamInputs(team_id=team.pk)
            )

        assert result.verdicts_checked == 1
        assert result.verdicts_corrected == 1
        produced = [call.kwargs["data"] for call in mock_producer.produce.call_args_list]
        assert produced == [
            {
                "team_id": team.pk,
                "distinct_id": "did-merged",
                "person_id": str(new_person.uuid),
                "condition": condition_hash,
                "matches": True,
                "source": f"cohort_filter_{condition_hash}",
            }
        ]

    async def test_leaves_already_correct_verdict_alone(self, team):
        condition_hash = "browser-set"
        await sync_to_async(Cohort.objects.create)(
            team=team,
            name="rt-browser",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "person",
                    "key": "$browser",
                    "conditionHash": condition_hash,
                    "bytecode": _is_set_bytecode("$browser"),
                }
            },
        )

        person = await sync_to_async(create_person)(
            team=team, distinct_ids=["did-synced"], properties={"$browser": "Chrome"}
        )
        # No merge: override maps the distinct_id to the same person the verdict already has.
        _insert_person_properties_verdict(team.pk, "did-synced", person.uuid, condition_hash, matches=True)
        _insert_override(team.pk, "did-synced", person.uuid)

        mock_producer = MagicMock()
        with patch(
            "posthog.temporal.messaging.reconcile_precalculated_data_workflow.get_producer",
            return_value=mock_producer,
        ):
            result = await ActivityEnvironment().run(
                reconcile_team_precalculated_person_properties_activity, ReconcileTeamInputs(team_id=team.pk)
            )

        assert result.verdicts_checked == 1
        assert result.verdicts_corrected == 0
        mock_producer.produce.assert_not_called()

    async def test_distinct_id_with_no_existing_verdict_is_skipped(self, team):
        # A condition never evaluated for a distinct_id isn't stale — it's the backfill's job
        # to populate, not this reconciliation's. Merely having an override must not conjure
        # a verdict out of nothing.
        condition_hash = "browser-set"
        await sync_to_async(Cohort.objects.create)(
            team=team,
            name="rt-browser",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "person",
                    "key": "$browser",
                    "conditionHash": condition_hash,
                    "bytecode": _is_set_bytecode("$browser"),
                }
            },
        )

        new_person = await sync_to_async(create_person)(
            team=team, distinct_ids=["did-never-evaluated"], properties={"$browser": "Chrome"}
        )
        _insert_override(team.pk, "did-never-evaluated", new_person.uuid)

        mock_producer = MagicMock()
        with patch(
            "posthog.temporal.messaging.reconcile_precalculated_data_workflow.get_producer",
            return_value=mock_producer,
        ):
            result = await ActivityEnvironment().run(
                reconcile_team_precalculated_person_properties_activity, ReconcileTeamInputs(team_id=team.pk)
            )

        assert result.verdicts_checked == 0
        assert result.verdicts_corrected == 0
        mock_producer.produce.assert_not_called()
