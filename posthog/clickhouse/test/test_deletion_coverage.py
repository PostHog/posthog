from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.models.deletion_targets import PERSONAL_DATA_TARGETS, TTL_ONLY_TABLES


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
