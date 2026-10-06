import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from asgiref.sync import async_to_sync
from clickhouse_driver import Client
from dagster import Failure, build_op_context
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.clickhouse.adhoc_events_deletion import ADHOC_EVENTS_DELETION_TABLE, ADHOC_EVENTS_DELETION_TABLE_SQL
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import LightweightDeleteMutationRunner, MutationWaiter, Query, get_cluster
from posthog.dags.common.s3_staging import S3StagingLocation
from posthog.dags.data_deletion_requests import (
    DeletionRequestContext,
    PersonRemovalContext,
    PropertyRemovalTarget,
    cleanup_property_removal_staging,
    complete_event_deletion,
    copy_property_removal_shard,
    data_deletion_request_event_removal,
    delete_event_removal_shard,
    delete_person_profiles_op,
    delete_property_removal_shard,
    finalize_deletion_request,
    get_event_removal_shards,
    get_property_removal_shards,
    reingest_property_removal_shard,
    verify_property_removal,
    verify_property_removal_shard,
)
from posthog.dags.deletes import deletes_job
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.data_deletion_request import DataDeletionRequest, ExecutionMode, RequestStatus, RequestType
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
from posthog.models.team import Team
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
from products.customer_analytics.backend.logic.membership_deletion import QUERY_SETTINGS, MembershipReconciliation
from products.customer_analytics.backend.models.team_customer_analytics_config import TeamCustomerAnalyticsConfig
from products.customer_analytics.backend.test.factories import create_account


@time_machine.travel("2025-02-01T00:00:00Z", tick=False)
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

    def _delete_events(self, request: DeletionRequestContext) -> None:
        shards = list(get_event_removal_shards(build_op_context(), self.cluster, request))
        deleted = [
            delete_event_removal_shard(build_op_context(), self.cluster, shard.value, request) for shard in shards
        ]
        complete_event_deletion(build_op_context(), self.cluster, request, deleted)

    def _rewrite_properties(
        self, request: DeletionRequestContext, targets: list[PropertyRemovalTarget], *, copy: bool = True
    ) -> list[dict]:
        stats = []
        for target in targets:
            if copy:
                copy_property_removal_shard(build_op_context(), self.cluster, target, request)
            delete_property_removal_shard(build_op_context(), self.cluster, target, request)
            reingest_property_removal_shard(build_op_context(), self.cluster, target, request)
            stats.append(verify_property_removal_shard(build_op_context(), self.cluster, target, request))
        verify_property_removal(build_op_context(), self.cluster, request, stats)
        return stats

    def _staged_property_files(self, request: DeletionRequestContext) -> list[tuple]:
        location = S3StagingLocation.for_data_deletion()
        args = location.s3_args(f"property_removal/{request.request_id}/*/*/data/*.native", "One")
        return self.cluster.any_host(Query(f"SELECT _path FROM s3({args}) WHERE _size > 0")).result()

    @parameterized.expand([("sync", False), ("queued", True)])
    def test_profile_deletion_removes_every_attached_id(self, _name: str, queued: bool) -> None:
        stage_membership_deletion(
            self.cluster,
            self.operation_id,
            [("events", False, "team_id = %(team_id)s AND event = 'only'", {"team_id": self.team.pk})],
        )
        with (
            patch("posthog.models.person.bulk_delete.queue_person_training_deletion"),
            self.assertLogs("posthog.clickhouse.cluster", level="INFO") as logs,
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
        assert "a-alias" not in "\n".join(logs.output)
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

    def test_staging_storage_without_proxy_does_not_block_person_deletion(self) -> None:
        stage_membership_deletion(
            self.cluster,
            self.operation_id,
            [("events", False, "team_id = %(team_id)s AND event = 'only'", {"team_id": self.team.pk})],
        )
        stage = MembershipReconciliation(self.cluster, self.operation_id)
        sync_execute(f"DROP TABLE {stage.read_table} SYNC")
        assert sync_execute(f"SELECT distinct_id FROM {stage.storage_table}") == [("a",)]
        other_team = Team.objects.create(organization=self.organization, name="other")
        other_person = create_person(team=other_team, distinct_ids=["z"])
        with patch("posthog.models.person.bulk_delete.queue_person_training_deletion"):
            for team, person in [(other_team, other_person), (self.team, self.person_a)]:
                result = delete_persons_profile(team.pk, [person], actor=None)
                assert result.failures == []
                assert result.deleted_count == 1
        assert sync_execute(f"SELECT distinct_id FROM {stage.storage_table}") == []

    def test_reassigned_id_survives_old_person_deletion(self) -> None:
        client = require_personhog_client()
        response = client.split_person(
            SplitPersonRequest(team_id=self.team.pk, person_id=self.person_a.pk, distinct_ids_to_split=["a"])
        )
        with patch("posthog.models.person.bulk_delete.queue_person_training_deletion"):
            result = delete_persons_profile(self.team.pk, [self.person_a], actor=None)
        assert result.failures == []
        assert result.deleted_count == 1
        assert [(key, did) for key, did, *_ in self._rows()] == [("acme", "a"), ("acme", "b"), ("other", "b")]
        assert get_person_by_uuid(self.team.pk, response.splits[0].new_person_uuid) is not None

    @parameterized.expand(
        [("profile_helper", False, False), ("queued_helper", False, True), ("person_removal_request", True, False)]
    )
    def test_membership_failure_keeps_profile_for_retry(self, _name: str, dagster_request: bool, queued: bool) -> None:
        original_call = LightweightDeleteMutationRunner.__call__

        def fail_person_a(runner: LightweightDeleteMutationRunner, client: Client) -> MutationWaiter:
            if "a" in runner.parameters.get("distinct_ids", []):
                return MutationWaiter(table=runner.table, mutation_ids=set())
            return original_call(runner, client)

        with (
            patch("posthog.models.person.bulk_delete.queue_person_training_deletion"),
            patch.object(LightweightDeleteMutationRunner, "__call__", autospec=True, side_effect=fail_person_a),
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
                if queued:
                    result = process_queued_person_deletion(
                        self.team.pk,
                        [str(self.person_a.uuid), str(self.person_b.uuid)],
                        delete_profile=True,
                        delete_recordings=False,
                        actor=None,
                        was_impersonated=False,
                        organization_id=None,
                    )
                else:
                    result = delete_persons_profile(self.team.pk, [self.person_a, self.person_b], actor=None)
                assert result.deleted_count == 1
                assert [(f.step, f.person_uuid) for f in result.failures] == [
                    (PersonDeletionStep.DELETE_MEMBERSHIP, self.person_a.uuid)
                ]
                assert result.retryable_errors == [self.person_a.uuid]
                assert get_person_by_uuid(self.team.pk, str(self.person_b.uuid)) is None
        assert get_person_by_uuid(self.team.pk, str(self.person_a.uuid)) is not None
        assert len(self._rows()) == (4 if dagster_request else 2)

    @parameterized.expand(
        [
            ("single_source", "only", [("acme", "a-alias"), ("acme", "b"), ("other", "b")]),
            ("multiple_sources", "first", [("acme", "a"), ("acme", "a-alias"), ("acme", "b"), ("other", "b")]),
        ]
    )
    def test_immediate_event_deletion(self, _name: str, event: str, expected: list[tuple[str, str]]) -> None:
        request = self._request([event])
        self._delete_events(request)
        assert [(key, did) for key, did, *_ in self._rows()] == expected
        if event == "first":
            row = next(row for row in self._rows() if row[:2] == ("acme", "b"))
            assert row[2:] == (self.start + timedelta(days=4), self.start + timedelta(days=4))
        self._delete_events(request)
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

    @parameterized.expand([("shard", "sharded_events_json"), ("reconciliation", SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE)])
    def test_retry_retains_keys_after_source_is_gone(self, _name: str, failed_table: str) -> None:
        request = DataDeletionRequest.objects.create(
            id=self.operation_id,
            team_id=self.team.pk,
            request_type=RequestType.EVENT_REMOVAL,
            events=["only"],
            start_time=self.start,
            end_time=self.end,
            status=RequestStatus.APPROVED,
        )
        original_call = LightweightDeleteMutationRunner.__call__

        def fail_delete(runner: LightweightDeleteMutationRunner, client: Client) -> MutationWaiter:
            if runner.table == failed_table:
                raise RuntimeError("delete failed")
            return original_call(runner, client)

        with patch.object(LightweightDeleteMutationRunner, "__call__", autospec=True, side_effect=fail_delete):
            result = data_deletion_request_event_removal.execute_in_process(
                run_config={"ops": {"load_deletion_request": {"config": {"request_id": self.operation_id}}}},
                resources={"cluster": self.cluster},
                raise_on_error=False,
            )
        assert not result.success
        request.refresh_from_db()
        assert request.status == RequestStatus.FAILED
        assert sync_execute(
            "SELECT count() FROM events WHERE team_id = %(team_id)s AND event = 'only'",
            {"team_id": self.team.pk},
        ) == [(0,)]
        ctx = result.output_for_node("load_deletion_request")
        shards = result.output_for_node("get_event_removal_shards")
        successful_steps = {event.step_key for event in result.all_events if event.is_step_success}
        deleted = [
            shard
            if f"delete_event_removal_shard[{key}]" in successful_steps
            else delete_event_removal_shard(build_op_context(), self.cluster, shard, ctx)
            for key, shard in shards.items()
        ]
        completed = complete_event_deletion(build_op_context(), self.cluster, ctx, deleted)
        finalize_deletion_request(build_op_context(), completed)
        request.refresh_from_db()
        assert request.status == RequestStatus.COMPLETED
        assert ("acme", "a") not in [row[:2] for row in self._rows()]
        assert len(self._rows()) == 3
        self._delete_events(ctx)
        assert len(self._rows()) == 3

    @parameterized.expand(
        [
            (f"{name}_{schema}", event, prop, count, index, native)
            for name, event, prop, count, index in [
                ("configured_single", "only", "$group_0", 3, 0),
                ("configured_multiple", "first", "$group_0", 4, 0),
                ("unrelated", "only", "unrelated", 4, 0),
                ("unconfigured_group", "only", "$group_1", 4, 0),
                ("person_property", "only", "person:email", 4, 0),
                ("previously_configured_group", "only", "$group_0", 3, 1),
            ]
            for schema, native in [("legacy", False), ("native", True)]
        ]
    )
    def test_property_removal(
        self, _name: str, event: str, property_name: str, expected_count: int, account_index: int, native: bool
    ) -> None:
        if native:
            sync_execute(
                "INSERT INTO sharded_events_json (team_id, event, uuid, timestamp, distinct_id, person_id, properties, inserted_at) "
                "SELECT team_id, event, uuid, timestamp, distinct_id, person_id, properties, inserted_at FROM sharded_events "
                "WHERE team_id = %(team_id)s",
                {"team_id": self.team.pk},
            )
            sync_execute(
                "DELETE FROM sharded_events WHERE team_id = %(team_id)s",
                {"team_id": self.team.pk},
                settings={"lightweight_deletes_sync": 2, "mutations_sync": 2},
            )
        if account_index != 0:
            self.account.delete()
            TeamCustomerAnalyticsConfig.objects.update_or_create(
                team=self.team, defaults={"account_group_type_index": account_index}
            )
        request = self._request([event], [] if property_name.startswith("person:") else [property_name])
        if property_name.startswith("person:"):
            request.person_properties = ["email"]
        source = "events_json" if native else "events"
        properties_column = "toJSONString(properties)" if native else "properties"
        property_query = f"SELECT event, {properties_column} FROM {source} WHERE team_id = %(team_id)s"
        before_properties = {
            name: json.loads(properties) for name, properties in sync_execute(property_query, {"team_id": self.team.pk})
        }
        assert set(before_properties) == {"only", "first", "last", "other"}
        for name, properties in before_properties.items():
            assert properties["$group_0"] == ("other" if name == "other" else "acme")
            assert properties["unrelated"] == "value"
        context = build_op_context()
        refused = native and property_name in ("$group_0", "unrelated")
        if refused:
            before = self._rows()
            with self.assertRaisesRegex(Failure, "property-rewrite machinery"):
                list(get_property_removal_shards(context, self.cluster, request))
            assert self._rows() == before
        else:
            targets = [output.value for output in get_property_removal_shards(context, self.cluster, request)]
            stats = self._rewrite_properties(request, targets)
            cleanup_property_removal_staging(context, self.cluster, request, stats)
            assert len(self._rows()) == expected_count
        rows = sync_execute(property_query, {"team_id": self.team.pk})
        assert len(rows) == 4
        for event_name, properties in rows:
            expected_properties = dict(before_properties[event_name])
            if event_name == event and not refused and property_name in ("$group_0", "unrelated"):
                expected_properties.pop(property_name)
            assert json.loads(properties) == expected_properties
        if property_name == "$group_0" and not refused:
            if event == "only":
                assert ("acme", "a") not in [row[:2] for row in self._rows()]
            else:
                row = next(row for row in self._rows() if row[:2] == ("acme", "b"))
                assert row[2:] == (self.start + timedelta(days=4), self.start + timedelta(days=4))

    def test_hogql_scoped_property_removal_keeps_out_of_scope_membership(self) -> None:
        sync_execute(
            f"INSERT INTO {PERSON_GROUP_MEMBERSHIP_TABLE} VALUES",
            [(self.team.pk, 0, "acme", "b", self.start, self.start + timedelta(days=4))],
            settings={"distributed_foreground_insert": 1},
        )
        request = self._request(["only", "first"], ["$group_0"])
        request.hogql_predicate = "distinct_id = 'a'"
        context = build_op_context()
        targets = [output.value for output in get_property_removal_shards(context, self.cluster, request)]
        stats = self._rewrite_properties(request, targets)
        cleanup_property_removal_staging(context, self.cluster, request, stats)
        assert self._rows() == [
            ("acme", "a-alias", self.start + timedelta(days=1), self.start + timedelta(days=1)),
            ("acme", "b", self.start, self.start + timedelta(days=4)),
            ("other", "b", self.start + timedelta(days=3), self.start + timedelta(days=3)),
        ]
        rows = sync_execute(
            "SELECT event, properties FROM events WHERE team_id = %(team_id)s AND event IN ('only', 'first') ORDER BY event",
            {"team_id": self.team.pk},
        )
        assert [(event, json.loads(properties)) for event, properties in rows] == [
            ("first", {"$group_0": "acme", "unrelated": "value"}),
            ("only", {"unrelated": "value"}),
        ]

    @parameterized.expand(
        [("after_source_delete", "sharded_events"), ("membership", SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE)]
    )
    def test_property_removal_retry_keeps_both_stages(self, _name: str, failed_table: str) -> None:
        request = self._request(["only"], ["$group_0"])
        target = PropertyRemovalTarget(table="sharded_events", shard=1, json_schema=False)
        copy_property_removal_shard(build_op_context(), self.cluster, target, request)
        stage = MembershipReconciliation(self.cluster, self.operation_id)
        assert sync_execute("EXISTS TABLE " + stage.storage_table) == [(0,)]
        original_call = LightweightDeleteMutationRunner.__call__

        def fail_delete(runner: LightweightDeleteMutationRunner, client: Client) -> MutationWaiter:
            if runner.table == failed_table:
                if failed_table == "sharded_events":
                    original_call(runner, client).wait(client)
                raise RuntimeError("delete response lost")
            return original_call(runner, client)

        with patch.object(LightweightDeleteMutationRunner, "__call__", autospec=True, side_effect=fail_delete):
            with self.assertRaisesRegex(Exception, "delete response lost"):
                stats = self._rewrite_properties(request, [target], copy=False)
                cleanup_property_removal_staging(build_op_context(), self.cluster, request, stats)
        assert self._staged_property_files(request)
        assert sync_execute(f"SELECT group_key, distinct_id FROM {stage.read_table}") == [("acme", "a")]
        assert sync_execute(
            "SELECT count() FROM events WHERE team_id = %(team_id)s AND event = 'only' "
            "AND JSONHas(properties, '$group_0')",
            {"team_id": self.team.pk},
        ) == [(0,)]

        stats = self._rewrite_properties(request, [target], copy=False)
        cleanup_property_removal_staging(build_op_context(), self.cluster, request, stats)
        assert self._staged_property_files(request) == []
        assert sync_execute("EXISTS TABLE " + stage.storage_table) == [(0,)]
        assert [(key, did) for key, did, *_ in self._rows()] == [("acme", "a-alias"), ("acme", "b"), ("other", "b")]
        rows = sync_execute(
            "SELECT uuid, properties FROM events WHERE team_id = %(team_id)s AND event = 'only'",
            {"team_id": self.team.pk},
        )
        assert [(uuid, json.loads(properties)) for uuid, properties in rows] == [
            (self.event_ids[0], {"unrelated": "value"})
        ]

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
        sync_execute(
            "INSERT INTO sharded_events (team_id, event, uuid, timestamp, distinct_id, person_id, properties, inserted_at) VALUES",
            [
                (
                    self.team.pk,
                    "first",
                    self.event_ids[1],
                    self.start,
                    f"untracked-{i}",
                    str(self.person_a.uuid),
                    json.dumps({f"$group_{index}": f"untracked-{i}-{index}" for index in range(5)}),
                    self.start,
                )
                for i in range(10)
            ],
        )
        if deletion == "deferred":
            request = self._request(["first"])
            request.execution_mode = ExecutionMode.DEFERRED.value
            self._delete_events(request)
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
        with patch.dict(QUERY_SETTINGS, {"max_rows_in_set": "2"}):
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
            for table in ("events", "events_json"):
                assert sync_execute(
                    f"SELECT count() FROM {table} WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
                ) == [(4,)]

    def test_interrupted_cleanup_keeps_person_deletion_working(self) -> None:
        stage_membership_deletion(
            self.cluster,
            self.operation_id,
            [("events", False, "team_id = %(team_id)s AND event = 'only'", {"team_id": self.team.pk})],
        )
        reconcile_membership_deletion(self.cluster, self.operation_id, [("events", False)])
        original_call = Query.__call__
        drops: list[str] = []

        def interrupt_second_drop(query: Query, client: Client) -> Any:
            if query.query.startswith("DROP TABLE"):
                drops.append(query.query)
                if query.query != drops[0]:
                    raise RuntimeError("cleanup interrupted")
            return original_call(query, client)

        with (
            patch.object(Query, "__call__", autospec=True, side_effect=interrupt_second_drop),
            self.assertRaises(ExceptionGroup),
        ):
            cleanup_membership_deletion(self.cluster, self.operation_id)
        with patch("posthog.models.person.bulk_delete.queue_person_training_deletion"):
            result = delete_persons_profile(self.team.pk, [self.person_a], actor=None)
        assert result.failures == []
        assert result.deleted_count == 1
        reconcile_membership_deletion(self.cluster, self.operation_id, [("events", False)])
        cleanup_membership_deletion(self.cluster, self.operation_id)

    @parameterized.expand([("missing", True), ("empty", False)])
    def test_missing_or_empty_tables_allow_existing_deletions(self, _name: str, missing: bool) -> None:
        sync_execute(f"TRUNCATE TABLE {SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE}")
        if missing:
            self._drop_membership_tables()
        self._delete_events(self._request(["only"]))
        with patch("posthog.models.person.bulk_delete.queue_person_training_deletion"):
            result = delete_persons_profile(self.team.pk, [self.person_a], actor=None)
        assert result.deleted_count == 1
        assert result.failures == []
        assert get_person_by_uuid(self.team.pk, str(self.person_a.uuid)) is None
        delete_team_membership(self.cluster, [self.team.pk])

    def _drop_membership_tables(self) -> None:
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
