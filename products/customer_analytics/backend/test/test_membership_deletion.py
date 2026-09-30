import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import Mock, patch

from django.test import override_settings

from asgiref.sync import async_to_sync
from dagster import Failure, build_op_context
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.clickhouse.adhoc_events_deletion import ADHOC_EVENTS_DELETION_TABLE, ADHOC_EVENTS_DELETION_TABLE_SQL
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import get_cluster
from posthog.dags.data_deletion_requests import (
    DeletionRequestContext,
    PersonRemovalContext,
    delete_person_profiles_op,
    execute_event_deletion,
    get_property_removal_shards,
    process_property_removal_shard,
    verify_property_removal,
)
from posthog.dags.deletes import deletes_job
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.data_deletion_request import ExecutionMode
from posthog.models.deletion_targets import UnsweepableRowsError
from posthog.models.person.bulk_delete import PersonDeletionStep, delete_persons_profile, process_queued_person_deletion
from posthog.models.person.util import get_person_by_uuid
from posthog.models.person_group_membership.sql import (
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL,
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_TABLE_SQL,
    PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY,
    PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_SQL,
    PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL,
    PERSON_GROUP_MEMBERSHIP_TABLE,
    SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
    SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE_SQL,
)
from posthog.models.team.util import _delete_persons_for_teams
from posthog.personhog_client.client import require_personhog_client
from posthog.personhog_client.proto import SplitPersonRequest
from posthog.temporal.delete_persons.delete_persons_workflow import DeletePersonsActivityInputs, delete_persons_activity
from posthog.test.persons import create_person

from products.customer_analytics.backend.facade.membership_deletion import (
    cleanup_membership_deletion,
    delete_team_membership,
    reconcile_membership_deletion,
    stage_membership_deletion,
)
from products.customer_analytics.backend.models.team_customer_analytics_config import TeamCustomerAnalyticsConfig
from products.customer_analytics.backend.test.factories import create_account


class TestMembershipDeletion(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(ADHOC_EVENTS_DELETION_TABLE_SQL(on_cluster=False))
        sync_execute(f"TRUNCATE TABLE {ADHOC_EVENTS_DELETION_TABLE}")
        self.cluster = get_cluster()
        self.operation_id = str(uuid4())
        self.addCleanup(cleanup_membership_deletion, self.cluster, self.operation_id)
        for table in (SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE, PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE):
            sync_execute(f"TRUNCATE TABLE {table}")
            self.addCleanup(sync_execute, f"TRUNCATE TABLE IF EXISTS {table}")
        TeamCustomerAnalyticsConfig.objects.update_or_create(team=self.team, defaults={"account_group_type_index": 0})
        self.account = create_account(team_id=self.team.pk, external_id="acme")
        self.person_a = create_person(team=self.team, distinct_ids=["a", "a-alias"])
        self.person_b = create_person(team=self.team, distinct_ids=["b"])
        self.start = datetime(2025, 1, 1, tzinfo=UTC)
        self.end = self.start + timedelta(days=10)
        self.event_ids = [uuid4() for _ in range(4)]
        sync_execute(
            "INSERT INTO sharded_events (team_id, event, uuid, timestamp, distinct_id, person_id, properties, inserted_at) VALUES",
            [
                (
                    self.team.pk,
                    event,
                    uuid,
                    self.start + timedelta(days=day),
                    did,
                    str(person.uuid),
                    json.dumps({"$group_0": key, "unrelated": "value"}),
                    self.start,
                )
                for event, uuid, day, did, person, key in [
                    ("only", self.event_ids[0], 1, "a", self.person_a, "acme"),
                    ("first", self.event_ids[1], 2, "b", self.person_b, "acme"),
                    ("last", self.event_ids[2], 4, "b", self.person_b, "acme"),
                    ("other", self.event_ids[3], 3, "b", self.person_b, "other"),
                ]
            ],
        )
        sync_execute(
            f"INSERT INTO {PERSON_GROUP_MEMBERSHIP_TABLE} VALUES",
            [
                (self.team.pk, 0, key, did, self.start + timedelta(days=first), self.start + timedelta(days=last))
                for key, did, first, last in [
                    ("acme", "a", 1, 1),
                    ("acme", "a-alias", 1, 1),
                    ("acme", "b", 2, 4),
                    ("other", "b", 3, 3),
                ]
            ],
            settings={"distributed_foreground_insert": 1},
        )

    def _rows(self) -> list[tuple]:
        return sync_execute(
            f"SELECT group_key, distinct_id, min(first_seen), max(last_seen) FROM {PERSON_GROUP_MEMBERSHIP_TABLE} "
            "WHERE team_id = %(team_id)s GROUP BY group_key, distinct_id ORDER BY group_key, distinct_id",
            {"team_id": self.team.pk},
        )

    def _request(self, events: list[str], properties: list[str] | None = None) -> DeletionRequestContext:
        return DeletionRequestContext(
            request_id=self.operation_id,
            team_id=self.team.pk,
            start_time=self.start,
            end_time=self.end,
            events=events,
            properties=properties or [],
            inserted_at_marker=self.end,
        )

    @parameterized.expand(
        [
            ("sync_legacy", False, False),
            ("queued_legacy", True, False),
            ("sync_tombstone", False, True),
            ("queued_tombstone", True, True),
        ]
    )
    def test_profile_deletion_removes_every_attached_id(self, _name: str, queued: bool, tombstone: bool) -> None:
        stage_membership_deletion(
            self.cluster,
            self.operation_id,
            [("events", False, "team_id = %(team_id)s AND event = 'only'", {"team_id": self.team.pk})],
        )
        with (
            override_settings(PERSON_DELETE_TOMBSTONE=tombstone),
            patch("posthog.models.person.bulk_delete.queue_person_training_deletion"),
        ):
            if queued:
                result = process_queued_person_deletion(
                    self.team.pk,
                    [str(self.person_a.uuid)],
                    delete_profile=True,
                    delete_recordings=False,
                    actor=None,
                    was_impersonated=False,
                    organization_id=None,
                )
            else:
                result = delete_persons_profile(self.team.pk, [self.person_a], actor=None)
        assert result.deleted_count == 1
        assert result.failures == []
        reconcile_membership_deletion(self.cluster, self.operation_id, [("events", False)])
        assert [(key, did) for key, did, *_ in self._rows()] == [("acme", "b"), ("other", "b")]
        retry = process_queued_person_deletion(
            self.team.pk,
            [str(self.person_a.uuid)],
            delete_profile=True,
            delete_recordings=False,
            actor=None,
            was_impersonated=False,
            organization_id=None,
        )
        assert retry.failures == []
        assert [(key, did) for key, did, *_ in self._rows()] == [("acme", "b"), ("other", "b")]

    @parameterized.expand([("legacy", False), ("tombstone", True)])
    def test_reassigned_id_survives_old_person_deletion(self, _name: str, tombstone: bool) -> None:
        client = require_personhog_client()
        response = client.split_person(
            SplitPersonRequest(team_id=self.team.pk, person_id=self.person_a.pk, distinct_ids_to_split=["a"])
        )
        with (
            override_settings(PERSON_DELETE_TOMBSTONE=tombstone),
            patch("posthog.models.person.bulk_delete.queue_person_training_deletion"),
        ):
            result = delete_persons_profile(self.team.pk, [self.person_a], actor=None)
        assert result.failures == []
        assert result.deleted_count == 1
        assert [(key, did) for key, did, *_ in self._rows()] == [("acme", "a"), ("acme", "b"), ("other", "b")]
        assert get_person_by_uuid(self.team.pk, response.splits[0].new_person_uuid) is not None

    @parameterized.expand([("profile_helper", False), ("person_removal_request", True)])
    def test_membership_failure_keeps_profile_for_retry(self, _name: str, dagster_request: bool) -> None:
        with (
            patch("posthog.models.person.bulk_delete.queue_person_training_deletion"),
            patch(
                "posthog.clickhouse.cluster.ClickhouseCluster.map_one_host_per_shard",
                return_value=Mock(result=lambda: {}),
            ),
        ):
            if dagster_request:
                removal = PersonRemovalContext(
                    request_id=self.operation_id,
                    team_id=self.team.pk,
                    person_uuids=[str(self.person_a.uuid)],
                    person_distinct_ids=[],
                    drop_profiles=True,
                    drop_events=False,
                    drop_recordings=False,
                )
                with self.assertRaisesRegex(Failure, "membership delete failed"):
                    delete_person_profiles_op(build_op_context(), removal)
            else:
                result = delete_persons_profile(self.team.pk, [self.person_a], actor=None)
                assert result.deleted_count == 0
                assert result.failures[0].step is PersonDeletionStep.DELETE_MEMBERSHIP
        assert get_person_by_uuid(self.team.pk, str(self.person_a.uuid)) is not None
        assert len(self._rows()) == 4

    @parameterized.expand(
        [
            ("single_source", "only", [("acme", "a-alias"), ("acme", "b"), ("other", "b")]),
            ("multiple_sources", "first", [("acme", "a"), ("acme", "a-alias"), ("acme", "b"), ("other", "b")]),
        ]
    )
    def test_immediate_event_deletion(self, _name: str, event: str, expected: list[tuple[str, str]]) -> None:
        request = self._request([event])
        execute_event_deletion(build_op_context(), self.cluster, request)
        assert [(key, did) for key, did, *_ in self._rows()] == expected
        if event == "first":
            row = next(row for row in self._rows() if row[:2] == ("acme", "b"))
            assert row[2:] == (self.start + timedelta(days=4), self.start + timedelta(days=4))
        execute_event_deletion(build_op_context(), self.cluster, request)
        assert [(key, did) for key, did, *_ in self._rows()] == expected

    @parameterized.expand([("selected_person", False), ("whole_team", True)])
    def test_temporal_purge_clears_membership_before_identity(self, _name: str, whole_team: bool) -> None:
        sync_execute(
            f"INSERT INTO {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} VALUES",
            [(self.team.pk, 0, 1, 1)],
            settings={"distributed_foreground_insert": 1},
        )
        environment = ActivityEnvironment()

        async def run_activity() -> tuple[int, bool]:
            return await environment.run(
                delete_persons_activity,
                DeletePersonsActivityInputs(team_id=self.team.pk, person_ids=[] if whole_team else [self.person_a.pk]),
            )

        deleted, should_continue = async_to_sync(run_activity)()
        assert deleted == (2 if whole_team else 1)
        assert should_continue is False
        assert [(key, did) for key, did, *_ in self._rows()] == ([] if whole_team else [("acme", "b"), ("other", "b")])
        assert sync_execute(
            f"SELECT enabled FROM {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        ) == [(1,)]

    def test_retry_retains_keys_after_source_is_gone(self) -> None:
        predicate = "team_id = %(team_id)s AND event = %(event)s"
        params = {"team_id": self.team.pk, "event": "only"}
        stage_membership_deletion(self.cluster, self.operation_id, [("events", False, predicate, params)])
        sync_execute(
            "ALTER TABLE sharded_events DELETE WHERE team_id = %(team_id)s AND event = %(event)s",
            params,
            settings={"mutations_sync": 2},
        )
        stage_membership_deletion(self.cluster, self.operation_id, [("events", False, predicate, params)])
        reconcile_membership_deletion(self.cluster, self.operation_id, [("events", False)])
        reconcile_membership_deletion(self.cluster, self.operation_id, [("events", False)])
        assert ("acme", "a") not in [row[:2] for row in self._rows()]
        assert len(self._rows()) == 3

    @parameterized.expand(
        [
            ("configured_single", "only", "$group_0", 3),
            ("configured_multiple", "first", "$group_0", 4),
            ("unrelated", "only", "unrelated", 4),
            ("unconfigured_group", "only", "$group_1", 4),
            ("person_property", "only", "person:email", 4),
        ]
    )
    def test_property_removal(self, _name: str, event: str, property_name: str, expected_count: int) -> None:
        request = self._request([event], [] if property_name.startswith("person:") else [property_name])
        if property_name.startswith("person:"):
            request.person_properties = ["email"]
        context = build_op_context()
        shards = list(get_property_removal_shards(context, self.cluster, request))
        stats = [process_property_removal_shard(context, self.cluster, shard.value, request) for shard in shards]
        verify_property_removal(context, self.cluster, request, stats)
        assert len(self._rows()) == expected_count
        if property_name == "$group_0":
            if event == "only":
                assert ("acme", "a") not in [row[:2] for row in self._rows()]
            else:
                row = next(row for row in self._rows() if row[:2] == ("acme", "b"))
                assert row[2:] == (self.start + timedelta(days=4), self.start + timedelta(days=4))

    def test_team_deletion_clears_membership_and_config(self) -> None:
        stage_membership_deletion(
            self.cluster, self.operation_id, [("events", False, "team_id = %(team_id)s", {"team_id": self.team.pk})]
        )
        sync_execute(
            f"INSERT INTO {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} VALUES",
            [(self.team.pk, 0, 1, 1)],
            settings={"distributed_foreground_insert": 1},
        )
        other_team_id = self.team.pk + 1000000
        sync_execute(
            f"INSERT INTO {PERSON_GROUP_MEMBERSHIP_TABLE} VALUES",
            [(other_team_id, 0, "acme", "other-tenant", self.start, self.start)],
            settings={"distributed_foreground_insert": 1},
        )
        sync_execute(
            f"INSERT INTO {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} VALUES",
            [(other_team_id, 0, 1, 1)],
            settings={"distributed_foreground_insert": 1},
        )
        _delete_persons_for_teams([self.team.pk])
        assert sync_execute(
            f"SELECT distinct_id FROM {PERSON_GROUP_MEMBERSHIP_TABLE} WHERE team_id = %(team_id)s",
            {"team_id": other_team_id},
        ) == [("other-tenant",)]
        assert sync_execute(
            f"SELECT enabled FROM {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} WHERE team_id = %(team_id)s",
            {"team_id": other_team_id},
        ) == [(1,)]
        assert get_person_by_uuid(self.team.pk, str(self.person_a.uuid)) is None
        assert get_person_by_uuid(self.team.pk, str(self.person_b.uuid)) is None
        reconcile_membership_deletion(self.cluster, self.operation_id, [("events", False)])
        assert self._rows() == []
        assert sync_execute(
            f"SELECT count() FROM {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        ) == [(0,)]
        delete_team_membership(self.cluster, [self.team.pk])

    @parameterized.expand(
        [("event_uuid", "event"), ("person_events", "person"), ("deferred", "deferred"), ("team", "team")]
    )
    def test_async_drain_reconciles_before_marking_verified(self, _name: str, deletion: str) -> None:
        if deletion == "deferred":
            request = self._request(["first"])
            request.execution_mode = ExecutionMode.DEFERRED.value
            execute_event_deletion(build_op_context(), self.cluster, request)
        else:
            kind, key = {
                "event": (DeletionType.Event, str(self.event_ids[1])),
                "person": (DeletionType.Person, str(self.person_a.uuid)),
                "team": (DeletionType.Team, str(self.team.pk)),
            }[deletion]
            AsyncDeletion.objects.create(team_id=self.team.pk, deletion_type=kind, key=key)
        sync_execute(
            f"INSERT INTO {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} VALUES",
            [(self.team.pk, 0, 1, 1)],
            settings={"distributed_foreground_insert": 1},
        )
        sync_execute(
            "INSERT INTO person_distinct_id_overrides (distinct_id, person_id, _timestamp, version) VALUES",
            [("watermark", str(uuid4()), datetime.now(UTC) + timedelta(days=1), 1)],
        )
        result = deletes_job.execute_in_process(
            run_config={
                "ops": {"create_pending_deletions_table": {"config": {"timestamp": datetime.now(UTC).isoformat()}}}
            },
            resources={"cluster": self.cluster},
        )
        assert result.success
        if deletion == "team":
            assert self._rows() == []
            assert sync_execute(f"SELECT count() FROM {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE}") == [(0,)]
        elif deletion == "person":
            assert ("acme", "a") not in [row[:2] for row in self._rows()]
        else:
            row = next(row for row in self._rows() if row[:2] == ("acme", "b"))
            assert row[2:] == (self.start + timedelta(days=4), self.start + timedelta(days=4))
        assert not AsyncDeletion.objects.filter(team_id=self.team.pk, delete_verified_at__isnull=True).exists()
        self.addCleanup(sync_execute, f"TRUNCATE TABLE {ADHOC_EVENTS_DELETION_TABLE}")

    @parameterized.expand([("default_refuses", False), ("all_sources_swept", True)])
    def test_native_source_cannot_be_silently_skipped(self, _name: str, sweep_native: bool) -> None:
        sync_execute(
            "INSERT INTO sharded_events_json (team_id, event, uuid, timestamp, distinct_id, person_id, properties, inserted_at) "
            "SELECT team_id, event, uuid, timestamp, distinct_id, person_id, properties, inserted_at FROM sharded_events WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )
        request = AsyncDeletion.objects.create(
            team_id=self.team.pk, deletion_type=DeletionType.Event, key=str(self.event_ids[0])
        )
        if sweep_native:
            result = deletes_job.execute_in_process(
                run_config={"ops": {"resolve_sweep_targets": {"config": {"skip_targets": []}}}},
                resources={"cluster": self.cluster},
            )
            assert result.success
            assert ("acme", "a") not in [row[:2] for row in self._rows()]
        else:
            with self.assertRaisesRegex(UnsweepableRowsError, "is skipped"):
                deletes_job.execute_in_process(resources={"cluster": self.cluster})
            request.refresh_from_db()
            assert request.delete_verified_at is None
            assert len(self._rows()) == 4

    def test_missing_tables_allow_existing_deletions(self) -> None:
        for sql in (
            PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_SQL,
            DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL,
            PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE_SQL,
            DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_TABLE_SQL,
            SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE_SQL,
        ):
            self.addCleanup(sync_execute, sql())
        sync_execute(f"DROP DICTIONARY {PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY} SYNC")
        for table in (
            PERSON_GROUP_MEMBERSHIP_TABLE,
            SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
            DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
            PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
        ):
            sync_execute(f"DROP TABLE {table} SYNC")
        execute_event_deletion(build_op_context(), self.cluster, self._request(["only"]))
        delete_team_membership(self.cluster, [self.team.pk])
