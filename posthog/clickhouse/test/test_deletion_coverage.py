from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.models.deletion_targets import (
    PERSON_ID_REWRITE_EXEMPT,
    PERSONAL_DATA_TARGETS,
    SQUASH_TARGETS,
    TTL_ONLY_TABLES,
)


class TestDeletionCoverage(ClickhouseTestMixin, BaseTest):
    def test_storage_tables_carrying_person_properties_are_swept_or_exempt(self):
        # A table that stores person_properties stores personal data, so deleting a person has to
        # reach it. flag_evaluations shipped without any scanner pointed at it precisely because
        # nothing forced that decision to be made out loud (#81002).
        #
        # Keyed on person_properties rather than person_id: person_id is on cohortpeople,
        # person_static_cohort, person_distinct_id2 and more, which makes for an exemption list too
        # long to carry any signal. person_properties is the events-mirror signature.
        #
        # tmp_ is excluded because the property-removal job's staging tables are created AS
        # sharded_events, so a leaked one would fail this with a misleading name.
        rows = sync_execute(
            """
            SELECT t.name
            FROM system.tables t
            INNER JOIN system.columns c ON c.database = t.database AND c.table = t.name
            WHERE t.database = %(database)s
              AND c.name = 'person_properties'
              AND t.engine LIKE '%%MergeTree%%'
              AND t.name NOT LIKE 'tmp\\_%%'
            ORDER BY t.name
            """,
            {"database": settings.CLICKHOUSE_DATABASE},
        )
        storage_tables = {row[0] for row in rows}
        assert storage_tables, "expected at least the events tables to declare person_properties"

        accounted_for = {target.data_table for target in PERSONAL_DATA_TARGETS} | TTL_ONLY_TABLES
        unaccounted = sorted(storage_tables - accounted_for)

        assert not unaccounted, (
            f"{unaccounted} store person_properties but no deletion sweep reaches them. Register each "
            "in PERSONAL_DATA_TARGETS (posthog/models/deletion_targets.py), or add it to "
            "TTL_ONLY_TABLES with the retention window you are accepting as its erasure bound. "
            "See docs/internal/clickhouse-deletion-coverage.md."
        )

    def test_every_personal_data_target_is_squashed_or_exempt(self):
        # A merge moves a distinct_id to another person, and a later deletion names only the
        # survivor, so a target the squash skips keeps its rows on the absorbed person until the
        # TTL drops them (#93035). The test above cannot catch that: it keys on person_properties,
        # which flag_evaluations does not declare, which is how flag_evaluations slipped through.
        skipped = {target.data_table for target in PERSONAL_DATA_TARGETS if not target.accepts_person_id_rewrite}
        unaccounted = sorted(skipped - PERSON_ID_REWRITE_EXEMPT)

        assert not unaccounted, (
            f"{unaccounted} are swept for person deletion, but squash_person_overrides never rewrites "
            "their person_id, so a merge strands rows on the person it absorbed. Set "
            "accepts_person_id_rewrite=True on each (posthog/models/deletion_targets.py), or add it to "
            "PERSON_ID_REWRITE_EXEMPT with the window you are accepting. "
            "See docs/internal/clickhouse-deletion-coverage.md."
        )

    def test_squash_targets_accept_an_alter_update_on_person_id(self):
        # The squash rewrites person_id with ALTER UPDATE, and ClickHouse refuses one on a column in
        # the sorting key or the partition key. A target marked accepts_person_id_rewrite whose key
        # carries person_id fails on the weekly job rather than here.
        #
        # Matched on the column name in system.columns rather than scanned out of the key
        # expression: that text both rejects an unrelated column whose name contains person_id and
        # misses the partition key entirely.
        params = {
            "database": settings.CLICKHOUSE_DATABASE,
            "tables": [target.data_table for target in SQUASH_TARGETS],
        }
        # Scoped to the tables that are actually here, because an optional target sits behind a
        # migration that may not have run on this deployment. Absent is fine; present without the
        # column is not.
        present = {
            table
            for [table] in sync_execute(
                "SELECT name FROM system.tables WHERE database = %(database)s AND name IN %(tables)s",
                params,
            )
        }
        assert present, "expected at least the events storage table to exist"

        rows = sync_execute(
            """
            SELECT table, is_in_sorting_key, is_in_partition_key
            FROM system.columns
            WHERE database = %(database)s AND table IN %(tables)s AND name = 'person_id'
            """,
            params,
        )
        # A target the squash rewrites but whose table has no person_id at all drops out of the
        # scan below and would pass unexamined, while the job still issues it an ALTER UPDATE.
        undeclared = sorted(present - {table for table, _, _ in rows})
        assert not undeclared, (
            f"{undeclared} are squash targets whose storage table declares no person_id, so the "
            "ALTER UPDATE the squash issues them cannot resolve its own target column."
        )

        offenders = sorted(table for table, in_sorting, in_partition in rows if in_sorting or in_partition)
        assert not offenders, (
            f"{offenders} are squash targets carrying person_id in their sorting or partition key, "
            "so the squash cannot assign it. Both are fixed once the table holds data, so this "
            "needs a new table rather than an ALTER."
        )
