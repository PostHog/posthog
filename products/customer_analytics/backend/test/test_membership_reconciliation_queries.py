import json
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.clickhouse.adhoc_events_deletion import ADHOC_EVENTS_DELETION_TABLE, ADHOC_EVENTS_DELETION_TABLE_SQL
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import get_cluster
from posthog.dags.deletes import (
    _DELETE_PREDICATE,
    AdhocEventDeletesDictionary,
    AdhocEventDeletesTable,
    PendingDeletesDictionary,
    PendingDeletesTable,
    _delete_predicate_params,
    _membership_scan_predicates,
)
from posthog.models.async_deletion import DeletionType
from posthog.models.deletion_targets import UnsweepableRowsError
from posthog.models.person_group_membership.sql import PERSON_GROUP_MEMBERSHIP_TABLE

from products.customer_analytics.backend.logic.membership_deletion import QUERY_SETTINGS, MembershipReconciliation


class TestMembershipReconciliationQueries(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cluster = get_cluster()
        self.reconciliation = MembershipReconciliation(self.cluster, str(uuid4()))
        self.addCleanup(self.reconciliation.cleanup)
        self.start = datetime(2025, 1, 1, tzinfo=UTC)

    def _drop_dictionary(self, dictionary: PendingDeletesDictionary | AdhocEventDeletesDictionary) -> None:
        self.cluster.map_all_hosts(dictionary.drop).result()

    def _select_schema(self, native: bool) -> None:
        self.native = native
        self.source = "events_json" if native else "events"
        self.storage = "sharded_events_json" if native else "sharded_events"

    def _insert_events(self, rows: list[tuple], *, person_mode: str = "full") -> None:
        insert = f"INSERT INTO {self.storage} (team_id, event, uuid, timestamp, distinct_id, person_id, properties, inserted_at, person_mode)"
        if self.native:
            for start in range(0, len(rows), 10):
                batch = rows[start : start + 10]
                values = ", ".join(f"%(row_{index})s" for index in range(len(batch)))
                sync_execute(
                    f"{insert} SELECT c1, c2, c3, toDateTime64(c4, 6, 'UTC'), c5, c6, c7, "
                    f"toDateTime64(c8, 6, 'UTC'), %(person_mode)s FROM values({values})",
                    {
                        f"row_{index}": tuple(
                            value.strftime("%Y-%m-%d %H:%M:%S.%f") if isinstance(value, datetime) else value
                            for value in row
                        )
                        for index, row in enumerate(batch)
                    }
                    | {"person_mode": person_mode},
                )
        else:
            sync_execute(f"{insert} VALUES", [(*row, person_mode) for row in rows])

    def _insert_membership(self, rows: list[tuple]) -> None:
        sync_execute(
            f"INSERT INTO {PERSON_GROUP_MEMBERSHIP_TABLE} VALUES",
            rows,
            settings={"distributed_foreground_insert": 1},
        )

    @parameterized.expand(
        [
            ("legacy_rows", False, 2, 64),
            ("native_rows", True, 2, 64),
            ("legacy_bytes", False, 100, 20000),
            ("native_bytes", True, 100, 20000),
            ("legacy_query_size", False, 1000, 1000, 200, 256 * 1024**2),
            ("native_query_size", True, 1000, 1000, 200, 256 * 1024**2),
        ]
    )
    def test_pages_membership_before_scanning_and_rebuilds_full_history(
        self, _name: str, native: bool, row_limit: int, key_length: int, key_count: int = 7, byte_limit: int = 65536
    ) -> None:
        self._select_schema(native)
        keys = [(f"account-{i:04d}-" + "x" * key_length, f"member-{i}") for i in range(key_count)]
        events = []
        for i, (key, did) in enumerate(keys):
            for day in [5] if i == 0 else [0, 5, 12]:
                events.append(
                    (
                        self.team.pk,
                        "delete" if day == 5 else "keep",
                        uuid4(),
                        self.start + timedelta(days=day),
                        did,
                        uuid4(),
                        json.dumps({f"$group_{0 if i < 3 else 4}": key, "$group_1": f"untracked-{i}-{day}"}),
                        self.start,
                    )
                )
        for team_id in (self.team.pk, self.team.pk + 1000000):
            for i in range(20):
                events.append(
                    (
                        team_id,
                        "delete",
                        uuid4(),
                        self.start + timedelta(days=5),
                        f"untracked-{i}",
                        uuid4(),
                        json.dumps({f"$group_{index}": f"untracked-{i}-{index}" for index in range(5)}),
                        self.start,
                    )
                )
        self._insert_events(events)
        self._insert_events(
            [
                (
                    self.team.pk,
                    "keep",
                    uuid4(),
                    self.start + timedelta(days=20),
                    keys[0][1],
                    uuid4(),
                    json.dumps({"$group_0": keys[0][0]}),
                    self.start,
                )
            ],
            person_mode="propertyless",
        )
        self._insert_membership(
            [
                (self.team.pk, 0 if i < 3 else 4, key, did, self.start, self.start + timedelta(days=12))
                for i, (key, did) in enumerate(keys)
            ]
            + [(self.team.pk + 2000000, 0, keys[0][0], keys[0][1], self.start, self.start)]
        )
        sources: list[tuple[str, bool, str, dict[str, object]]] = [
            (self.source, self.native, "team_id = %(team_id)s AND event = 'delete'", {"team_id": self.team.pk})
        ]
        with patch.dict(
            QUERY_SETTINGS,
            {"max_rows_in_set": str(row_limit), "max_bytes_in_set": str(byte_limit), "max_query_size": "262144"},
        ):
            self.reconciliation.stage(
                [
                    (
                        "source_that_must_not_be_read",
                        self.native,
                        "team_id = %(team_id)s",
                        {"team_id": self.team.pk + 1000000},
                    )
                ]
            )
            self.reconciliation.stage(sources)
            assert sync_execute(f"SELECT count() FROM {self.reconciliation.read_table}") == [(key_count,)]
            sync_execute(
                f"DELETE FROM {self.storage} WHERE team_id = %(team_id)s AND event = 'delete'",
                {"team_id": self.team.pk},
                settings={"lightweight_deletes_sync": 2, "mutations_sync": 2},
            )
            self.reconciliation.stage(sources)
            self.reconciliation.reconcile([(self.source, self.native)])
        assert sync_execute(
            f"SELECT group_key, distinct_id, min(first_seen), max(last_seen) FROM {PERSON_GROUP_MEMBERSHIP_TABLE} "
            "WHERE team_id = %(team_id)s GROUP BY group_key, distinct_id ORDER BY group_key",
            {"team_id": self.team.pk},
        ) == [(key, did, self.start, self.start + timedelta(days=12)) for key, did in keys[1:]]
        assert sync_execute(
            f"SELECT count() FROM {PERSON_GROUP_MEMBERSHIP_TABLE} WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk + 2000000},
        ) == [(1,)]

    def test_parser_failure_keeps_source_rows_and_redacts_identifiers(self) -> None:
        self._select_schema(False)
        identifier = "private@example.com"
        group_key = identifier + "x" * 64000
        self._insert_events(
            [
                (
                    self.team.pk,
                    "delete",
                    uuid4(),
                    self.start,
                    identifier,
                    uuid4(),
                    json.dumps({"$group_0": group_key}),
                    self.start,
                )
            ]
        )
        self._insert_membership([(self.team.pk, 0, group_key, identifier, self.start, self.start)])
        with (
            patch.dict(QUERY_SETTINGS, {"max_query_size": "4096"}),
            self.assertLogs(level="INFO") as logs,
            self.assertRaises(ServerException) as error,
        ):
            self.reconciliation.stage([(self.source, False, "team_id = %(team_id)s", {"team_id": self.team.pk})])
        assert error.exception.code == 62
        assert identifier not in "\n".join(logs.output)
        assert sync_execute(
            f"SELECT count() FROM {self.source} WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
        ) == [(1,)]

    @parameterized.expand([("legacy", False), ("native", True)])
    def test_membership_predicates_work_without_source_node_dictionaries(self, _name: str, native: bool) -> None:
        self._select_schema(native)
        sync_execute(ADHOC_EVENTS_DELETION_TABLE_SQL(on_cluster=False))
        sync_execute(f"TRUNCATE TABLE {ADHOC_EVENTS_DELETION_TABLE}")
        pending = PendingDeletesDictionary(source=PendingDeletesTable(timestamp=datetime.now(UTC)))
        adhoc = AdhocEventDeletesDictionary(source=AdhocEventDeletesTable())
        self.cluster.map_all_hosts(pending.source.create).result()
        self.addCleanup(lambda: self.cluster.map_all_hosts(pending.source.drop).result())
        for dictionary in (pending, adhoc):
            self.addCleanup(self._drop_dictionary, dictionary)
        cutoff = self.start + timedelta(days=5)
        person_id, event_id = uuid4(), uuid4()
        adhoc_id, cancelled_id = uuid4(), uuid4()
        sync_execute(
            pending.source.populate_query,
            [
                (1, DeletionType.Person, str(person_id), None, cutoff, None, None, self.team.pk),
                (2, DeletionType.Event, str(event_id), None, cutoff, None, None, self.team.pk),
                (3, DeletionType.Team, str(self.team.pk + 1000000), None, cutoff, None, None, self.team.pk + 1000000),
            ],
        )
        sync_execute(
            f"INSERT INTO {ADHOC_EVENTS_DELETION_TABLE} (team_id, uuid, created_at, is_deleted, deleted_at) VALUES",
            [
                (self.team.pk, adhoc_id, cutoff, 0, datetime.now(UTC)),
                (self.team.pk, cancelled_id, cutoff, 0, datetime.now(UTC) - timedelta(days=1)),
                (self.team.pk, cancelled_id, cutoff, 1, datetime.now(UTC)),
            ],
        )
        for dictionary in (pending, adhoc):
            self.cluster.map_all_hosts(
                partial(dictionary.create, shards=1, max_execution_time=60, max_memory_usage=128 * 1024**2)
            ).result()
            self.cluster.map_all_hosts(dictionary.load).result()
        later = cutoff + timedelta(microseconds=1)
        rows = [
            ("person_bound", self.team.pk, person_id, uuid4(), cutoff, cutoff),
            ("person_null_insert", self.team.pk, person_id, uuid4(), cutoff, None),
            ("person_late_timestamp", self.team.pk, person_id, uuid4(), later, cutoff),
            ("person_late_insert", self.team.pk, person_id, uuid4(), cutoff, later),
            ("event_unbounded", self.team.pk, uuid4(), event_id, later, later),
            ("adhoc_bound", self.team.pk, uuid4(), adhoc_id, cutoff, cutoff),
            ("adhoc_null_insert", self.team.pk, uuid4(), adhoc_id, later, None),
            ("adhoc_late_timestamp", self.team.pk, uuid4(), adhoc_id, later, cutoff),
            ("adhoc_late_insert", self.team.pk, uuid4(), adhoc_id, cutoff, later),
            ("adhoc_cancelled", self.team.pk, uuid4(), cancelled_id, cutoff, cutoff),
            ("other_tenant", self.team.pk + 2000000, person_id, event_id, cutoff, cutoff),
            ("whole_team", self.team.pk + 1000000, person_id, uuid4(), cutoff, cutoff),
        ]
        if native:
            rows = [row for row in rows if row[5] is not None]
        self._insert_events(
            [
                (team, did, event, timestamp, did, person, json.dumps({"$group_0": "account"}), inserted)
                for did, team, person, event, timestamp, inserted in rows
            ]
        )
        expected = {
            "person_bound",
            "event_unbounded",
            "adhoc_bound",
            "adhoc_late_timestamp",
        }
        if not native:
            expected |= {"person_null_insert", "adhoc_null_insert"}
        assert {
            row[0]
            for row in sync_execute(
                f"SELECT distinct_id FROM {self.source} WHERE ({_DELETE_PREDICATE}) AND team_id != %(deleted_team)s",
                {**_delete_predicate_params(pending, adhoc), "deleted_team": self.team.pk + 1000000},
            )
        } == expected
        with patch("posthog.dags.deletes._MEMBERSHIP_REQUEST_PAGE_SIZE", 2):
            predicates = list(_membership_scan_predicates(self.cluster, pending, adhoc))
        for dictionary in (pending, adhoc):
            self.cluster.map_all_hosts(dictionary.drop).result()
        with self.assertRaisesRegex(ServerException, "Dictionary"):
            sync_execute(
                f"SELECT distinct_id FROM {self.source} WHERE {_DELETE_PREDICATE}",
                _delete_predicate_params(pending, adhoc),
            )
        selected = {
            row[0]
            for batch in predicates
            for row in sync_execute(f"SELECT distinct_id FROM {self.source} WHERE {batch.predicate}", batch.parameters)
        }
        assert selected == expected
        self._insert_membership([(team, 0, "account", did, self.start, self.start) for did, team, *_ in rows])
        refused = 0
        with patch.dict(QUERY_SETTINGS, {"max_rows_in_set": "2"}):
            for batch in predicates:
                sources = [(self.source, self.native, batch.predicate, batch.parameters)]
                try:
                    self.reconciliation.refuse_unswept_sources(sources)
                except UnsweepableRowsError:
                    refused += 1
                self.reconciliation.stage(sources)
        assert refused > 0
        assert set(sync_execute(f"SELECT distinct_id FROM {self.reconciliation.read_table}")) == {
            (did,) for did in expected
        }
        assert sync_execute(
            f"SELECT count() FROM {self.source} WHERE team_id IN %(teams)s",
            {"teams": (self.team.pk, self.team.pk + 1000000, self.team.pk + 2000000)},
        ) == [(len(rows),)]
