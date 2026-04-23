import re
from datetime import datetime
from typing import Any

import pytest
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    flush_persons_and_events,
    get_indexes_from_explain,
)

from django.test import override_settings

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.models import PropertyDefinition
from posthog.models.group.util import create_group
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.data_warehouse.backend.models import DataWarehouseCredential, DataWarehouseJoin, DataWarehouseTable


class TestPropertyTypes(BaseTest):
    snapshot: Any
    maxDiff = None

    def setUp(self):
        super().setUp()
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:1",
            properties={"name": "org1", "inty": 1},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="$screen_height",
            defaults={"property_type": "Numeric"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="$screen_width",
            defaults={"property_type": "Numeric"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="bool",
            defaults={"property_type": "Boolean"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="tickets",
            defaults={"property_type": "Numeric"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="provided_timestamp",
            defaults={"property_type": "DateTime"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="$initial_browser",
            defaults={"property_type": "String"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.GROUP,
            name="inty",
            defaults={"property_type": "Numeric", "group_type_index": 0},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.GROUP,
            name="group_boolean",
            defaults={"property_type": "Boolean", "group_type_index": 0},
        )

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_property_types_event(self):
        printed = self._print_select(
            "select properties.$screen_width * properties.$screen_height, properties.bool from events"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_property_types_person_raw(self):
        printed = self._print_select(
            "select properties.tickets, properties.provided_timestamp, properties.$initial_browser from raw_persons"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_property_types_person(self):
        printed = self._print_select(
            "select properties.tickets, properties.provided_timestamp, properties.$initial_browser from raw_persons"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_property_types_combined(self):
        printed = self._print_select("select properties.$screen_width * person.properties.tickets from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_property_types_event_person_poe_off(self):
        printed = self._print_select("select person.properties.provided_timestamp from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_resolve_property_types_event_person_poe_on(self):
        printed = self._print_select("select person.properties.provided_timestamp from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_group_property_types(self):
        printed = self._print_select("select organization.properties.inty from events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_group_boolean_property_types(self):
        printed = self._print_select(
            """select
            organization.properties.group_boolean = true,
            organization.properties.group_boolean = false,
            organization.properties.group_boolean is null
            from events"""
        )
        assert printed == self.snapshot
        assert (
            "SELECT ifNull(equals(toBool(transform(toString(events__group_0.properties___group_boolean), hogvar, hogvar, NULL)), 1), 0), ifNull(equals(toBool(transform(toString(events__group_0.properties___group_boolean), hogvar, hogvar, NULL)), 0), 0), isNull(toBool(transform(toString(events__group_0.properties___group_boolean), hogvar, hogvar, NULL)))"
            in re.sub(r"%\(hogql_val_\d+\)s", "hogvar", printed)
        )

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_group_types_are_the_same_in_persons_inlined_subselect(self):
        expr = parse_select(
            """select table_a.id from
                    (select
                        events.timestamp as id,
                        organization.properties.group_boolean = true,
                        organization.properties.group_boolean = false,
                        organization.properties.group_boolean is null
                    from events) as table_a
            join persons on table_a.id = persons.id and persons.id in (select
                        events.timestamp as id,
                        organization.properties.group_boolean = true,
                        organization.properties.group_boolean = false,
                        organization.properties.group_boolean is null
                    from events)"""
        )
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        query = re.sub(r"hogql_val_\d+", "hogql_val", query)
        # We're searching for the two subselects and making sure they are exactly the same
        results = re.findall(
            rf"SELECT toTimeZone\(events\.timestamp.*?WHERE equals\(events\.team_id, {self.team.id}\)\)", query
        )
        assert results[0] == results[1]

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_data_warehouse_person_property_types(self):
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="extended_properties",
            columns={
                "string_prop": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
                "int_prop": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
                "bool_prop": {"hogql": "BooleanDatabaseField", "clickhouse": "Nullable(Bool)"},
            },
            credential=credential,
            url_pattern="",
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="extended_properties",
            joining_table_key="string_prop",
            field_name="extended_properties",
        )

        printed = self._print_select(
            "select persons.extended_properties.string_prop, persons.extended_properties.int_prop, persons.extended_properties.bool_prop AS bool_prop from persons WHERE bool_prop = true"
        )

        assert printed == self.snapshot

    def _print_select(self, select: str):
        expr = parse_select(select)
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)


# ── Timezone index pruning tests ──────────────────────────────────────────────
#
# The events table uses:
#     PARTITION BY toYYYYMM(timestamp)
#     ORDER BY (team_id, toDate(timestamp), event, ...)
#
# HogQL wraps timestamp fields with toTimeZone(timestamp, tz) for timezone
# support (see PropertySwapper.visit_field). ClickHouse can't derive partition
# or primary key bounds from toTimeZone() comparisons. Since toTimeZone only
# changes display metadata (not the underlying epoch), we move the timezone
# from the field side to the constant side in top-level WHERE range
# comparisons, letting the planner see bare timestamp for pruning.


def _get_index_by_type(indexes: list[dict], type_name: str) -> dict | None:
    for idx in indexes:
        if idx.get("Type") == type_name:
            return idx
    return None


class TestTimezoneIndexPruning(ClickhouseTestMixin, BaseTest):
    """
    Verify that timezone-aware date filters allow ClickHouse to prune
    partitions and use primary key indexes on the events table.
    """

    def setUp(self):
        super().setUp()
        # Create events across multiple months so ClickHouse produces
        # meaningful EXPLAIN output (otherwise it optimizes to NullSource)
        for month in range(1, 7):
            for day_offset in range(5):
                _create_event(
                    team=self.team,
                    distinct_id=f"user_{day_offset}",
                    event="$pageview",
                    timestamp=datetime(2024, month, 10 + day_offset),
                )
        flush_persons_and_events()

    def _compile_hogql(self, hogql: str, timezone: str = "UTC") -> tuple[str, dict]:
        self.team.timezone = timezone
        self.team.save()
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        node = parse_select(hogql)
        clickhouse_sql, _ = prepare_and_print_ast(node, context=context, dialect="clickhouse")
        return clickhouse_sql, context.values

    def test_bare_timestamp_prunes_partition_and_primary_key(self):
        """Bare timestamp comparisons allow partition and primary key pruning."""
        sql = (
            f"SELECT count() FROM events "
            f"WHERE team_id = {self.team.pk} "
            f"AND timestamp >= '2024-03-01' AND timestamp < '2024-04-01'"
        )
        indexes = get_indexes_from_explain(sql)

        partition = _get_index_by_type(indexes, "Partition")
        assert partition is not None
        assert partition.get("Condition") != "true", (
            f"Partition pruning should work with bare timestamp, got Condition={partition.get('Condition')!r}"
        )

        primary_key = _get_index_by_type(indexes, "PrimaryKey")
        assert primary_key is not None
        pk_keys = primary_key.get("Keys", [])
        assert any("toDate(timestamp)" in k for k in pk_keys), (
            f"PrimaryKey should use toDate(timestamp), got Keys={pk_keys}"
        )
        assert primary_key.get("Condition") != "true"

    @parameterized.expand(["UTC", "America/New_York"])
    def test_toTimeZone_breaks_partition_and_pk_pruning(self, tz):
        """toTimeZone(timestamp, tz) breaks partition pruning and PK date usage.

        If this test starts failing, ClickHouse has learned to derive
        toYYYYMM(timestamp) / toDate(timestamp) bounds from toTimeZone()
        comparisons, and we can remove the toTimeZone-stripping workaround
        entirely (PropertySwapper.visit_compare_operation).
        """
        sql = (
            f"SELECT count() FROM events "
            f"WHERE team_id = {self.team.pk} "
            f"AND toTimeZone(timestamp, '{tz}') >= '2024-03-01' "
            f"AND toTimeZone(timestamp, '{tz}') < '2024-04-01'"
        )
        indexes = get_indexes_from_explain(sql)

        partition = _get_index_by_type(indexes, "Partition")
        assert partition is not None
        assert partition.get("Condition") == "true", (
            f"tz={tz}: ClickHouse is now pruning partitions with toTimeZone — "
            f"the workaround may be removable. "
            f"Partition Condition={partition.get('Condition')!r}"
        )

    def test_hogql_compiled_query_has_partition_pruning(self):
        """The HogQL pipeline strips toTimeZone from WHERE comparisons to restore pruning."""
        sql, values = self._compile_hogql(
            "SELECT count() FROM events WHERE timestamp >= '2024-03-01' AND timestamp < '2024-04-01'",
            timezone="America/New_York",
        )
        indexes = get_indexes_from_explain(sql, values)

        partition = _get_index_by_type(indexes, "Partition")
        assert partition is not None
        assert partition.get("Condition") != "true", (
            f"Expected partition pruning. Partition Condition={partition.get('Condition')!r}"
        )

        primary_key = _get_index_by_type(indexes, "PrimaryKey")
        assert primary_key is not None
        pk_keys = primary_key.get("Keys", [])
        assert any("toDate(timestamp)" in k for k in pk_keys), (
            f"Expected PK to use toDate(timestamp), got Keys={pk_keys}"
        )

    def test_toTimeZone_stripped_from_where_but_kept_in_select(self):
        """toTimeZone should be stripped from top-level WHERE range comparisons
        but preserved in SELECT expressions and inside function calls."""
        sql, _ = self._compile_hogql(
            "SELECT timestamp FROM events WHERE timestamp >= '2024-03-01' AND timestamp < '2024-04-01'",
            timezone="America/New_York",
        )
        where_clause = sql.split("WHERE")[1]
        select_clause = sql.split("WHERE")[0]
        assert "toTimeZone" not in where_clause, f"Expected toTimeZone stripped from WHERE, got:\n{where_clause}"
        assert "toTimeZone" in select_clause, f"Expected toTimeZone in SELECT for display, got:\n{select_clause}"

    def test_toTimeZone_not_stripped_in_join_on(self):
        """toTimeZone should NOT be stripped from JOIN ON comparisons — only WHERE benefits from pruning."""
        sql, _ = self._compile_hogql(
            "SELECT e.timestamp FROM events e LEFT JOIN events e2 "
            "ON e.person_id = e2.person_id AND e2.timestamp >= e.timestamp "
            "WHERE e.timestamp >= '2024-03-01' AND e.timestamp < '2024-04-01'",
            timezone="America/New_York",
        )
        # The JOIN ON greaterOrEquals should still have toTimeZone wrapping
        assert re.search(r"greaterOrEquals\(toTimeZone\(", sql), (
            f"Expected toTimeZone preserved in JOIN ON greaterOrEquals, got:\n{sql}"
        )
        # The WHERE comparisons should have toTimeZone stripped (bare e.timestamp)
        assert re.search(r"greaterOrEquals\(e\.timestamp,", sql), (
            f"Expected bare e.timestamp in WHERE greaterOrEquals, got:\n{sql}"
        )
        assert re.search(r"less\(e\.timestamp,", sql), f"Expected bare e.timestamp in WHERE less, got:\n{sql}"

    def test_toTimeZone_not_stripped_inside_function_calls(self):
        """toTimeZone should NOT be stripped from comparisons inside function calls."""
        sql, _ = self._compile_hogql(
            "SELECT if(timestamp >= '2024-03-01', 'yes', 'no') FROM events",
            timezone="America/New_York",
        )
        assert "toTimeZone" in sql, f"Expected toTimeZone preserved inside if(), got:\n{sql}"

        # Mix: WHERE comparison (stripped) + nested in if() in SELECT (preserved)
        sql, _ = self._compile_hogql(
            "SELECT if(timestamp >= '2024-01-01', 'new', 'old') FROM events "
            "WHERE timestamp >= '2024-03-01' AND timestamp < '2024-04-01'",
            timezone="America/New_York",
        )
        where_clause = sql.split("WHERE")[1]
        select_clause = sql.split("WHERE")[0]
        assert "toTimeZone" not in where_clause, f"Expected toTimeZone stripped from WHERE, got:\n{where_clause}"
        assert "toTimeZone" in select_clause, f"Expected toTimeZone preserved in SELECT if(), got:\n{select_clause}"

    def test_subquery_in_where_does_not_inherit_stripping(self):
        """A subquery's SELECT inside a WHERE should NOT inherit stripping from the outer WHERE."""
        sql, _ = self._compile_hogql(
            "SELECT count() FROM events "
            "WHERE timestamp >= (SELECT min(timestamp) FROM events WHERE timestamp >= '2024-01-01')",
            timezone="America/New_York",
        )
        # The outer WHERE >= should strip toTimeZone from events.timestamp
        assert re.search(r"greaterOrEquals\(events\.timestamp,", sql), (
            f"Expected bare events.timestamp in outer WHERE, got:\n{sql}"
        )
        # The inner subquery's SELECT min(timestamp) should still have toTimeZone
        assert re.search(r"min\(toTimeZone\(", sql), f"Expected toTimeZone preserved in subquery SELECT, got:\n{sql}"
        # The inner WHERE should also strip toTimeZone
        assert re.search(r"greaterOrEquals\(events\.timestamp, toDateTime64", sql), (
            f"Expected bare events.timestamp in inner WHERE too, got:\n{sql}"
        )

    def test_toTimeZone_preserved_in_having(self):
        """HAVING should preserve toTimeZone — only WHERE/PREWHERE benefits from pruning."""
        sql, _ = self._compile_hogql(
            "SELECT event, max(timestamp) as max_ts FROM events "
            "WHERE timestamp >= '2024-03-01' AND timestamp < '2024-04-01' "
            "GROUP BY event HAVING max(timestamp) >= '2024-03-15'",
            timezone="America/New_York",
        )
        # The HAVING max(timestamp) comparison should preserve toTimeZone
        assert re.search(r"HAVING.*toTimeZone", sql), f"Expected toTimeZone preserved in HAVING, got:\n{sql}"

    def _assert_correct_results(self, hogql: str, timezone: str, expected_count: int):
        self.team.timezone = timezone
        self.team.save()
        response = execute_hogql_query(hogql, team=self.team)
        assert response.results is not None
        assert response.results[0][0] == expected_count, (
            f"tz={timezone}: expected {expected_count}, got {response.results[0][0]}"
        )

    def test_dst_boundary_does_not_drop_events(self):
        """America/New_York DST switch: events near midnight must not be missed."""
        _create_event(
            team=self.team, distinct_id="dst_user", event="dst_test", timestamp=datetime(2024, 3, 10, 5, 30, 0)
        )
        _create_event(
            team=self.team, distinct_id="dst_user", event="dst_test", timestamp=datetime(2024, 3, 10, 6, 30, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'dst_test' AND timestamp >= '2024-03-10' AND timestamp < '2024-03-11'"
        self._assert_correct_results(hogql, timezone="America/New_York", expected_count=2)

    def test_positive_utc_offset_does_not_drop_events(self):
        """Asia/Tokyo (UTC+9): midnight Tokyo = 15:00 UTC the previous day."""
        _create_event(
            team=self.team, distinct_id="tokyo_user", event="tokyo_test", timestamp=datetime(2024, 2, 29, 15, 30, 0)
        )
        _create_event(
            team=self.team, distinct_id="tokyo_user", event="tokyo_test", timestamp=datetime(2024, 3, 1, 14, 0, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'tokyo_test' AND timestamp >= '2024-03-01' AND timestamp < '2024-03-02'"
        self._assert_correct_results(hogql, timezone="Asia/Tokyo", expected_count=2)

    def test_utc_returns_correct_results(self):
        _create_event(
            team=self.team, distinct_id="utc_user", event="utc_test", timestamp=datetime(2024, 3, 1, 0, 30, 0)
        )
        _create_event(
            team=self.team, distinct_id="utc_user", event="utc_test", timestamp=datetime(2024, 3, 1, 23, 30, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'utc_test' AND timestamp >= '2024-03-01' AND timestamp < '2024-03-02'"
        self._assert_correct_results(hogql, timezone="UTC", expected_count=2)

    def test_brazil_historical_dst_does_not_drop_events(self):
        """Brazil dropped DST in 2019. Events during the old DST period must still work."""
        _create_event(
            team=self.team, distinct_id="brazil_user", event="brazil_test", timestamp=datetime(2018, 11, 15, 2, 30, 0)
        )
        _create_event(
            team=self.team, distinct_id="brazil_user", event="brazil_test", timestamp=datetime(2018, 11, 15, 12, 0, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'brazil_test' AND timestamp >= '2018-11-15' AND timestamp < '2018-11-16'"
        self._assert_correct_results(hogql, timezone="America/Sao_Paulo", expected_count=2)

    def test_half_hour_offset_does_not_drop_events(self):
        """Asia/Kolkata (UTC+5:30): midnight Kolkata = 18:30 UTC the previous day."""
        _create_event(
            team=self.team, distinct_id="kolkata_user", event="kolkata_test", timestamp=datetime(2024, 2, 29, 18, 30, 0)
        )
        _create_event(
            team=self.team, distinct_id="kolkata_user", event="kolkata_test", timestamp=datetime(2024, 3, 1, 17, 0, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'kolkata_test' AND timestamp >= '2024-03-01' AND timestamp < '2024-03-02'"
        self._assert_correct_results(hogql, timezone="Asia/Kolkata", expected_count=2)

    def test_lord_howe_half_hour_dst_does_not_drop_events(self):
        """Australia/Lord_Howe: 30-minute DST shift (UTC+10:30 → UTC+11)."""
        _create_event(
            team=self.team, distinct_id="lhi_user", event="lhi_test", timestamp=datetime(2024, 1, 15, 13, 0, 0)
        )
        _create_event(
            team=self.team, distinct_id="lhi_user", event="lhi_test", timestamp=datetime(2024, 1, 15, 22, 0, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'lhi_test' AND timestamp >= '2024-01-16' AND timestamp < '2024-01-17'"
        self._assert_correct_results(hogql, timezone="Australia/Lord_Howe", expected_count=2)

    def test_constant_gets_timezone_annotation(self):
        """Bare string constants get wrapped with toDateTime64(..., 6, tz)."""
        sql, values = self._compile_hogql(
            "SELECT count() FROM events WHERE timestamp >= '2024-03-01' AND timestamp < '2024-04-01'",
            timezone="America/New_York",
        )
        assert "toDateTime64" in sql, f"Expected toDateTime64 wrapping on constants, got:\n{sql}"
        assert "America/New_York" in values.values(), f"Expected timezone in parameterized values, got:\n{values}"

    def test_alias_preserved_when_recursing_into_assumeNotNull(self):
        """Alias wrappers on assumeNotNull(toDateTime(...)) constants must be preserved."""
        from posthog.hogql import ast as ast_module
        from posthog.hogql.transforms.property_types import PropertySwapper

        inner_call = ast_module.Call(name="toDateTime", args=[ast_module.Constant(value="2024-03-01")])
        assume_call = ast_module.Call(name="assumeNotNull", args=[inner_call])
        aliased = ast_module.Alias(alias="date_from", expr=assume_call)

        result = PropertySwapper._ensure_constant_has_timezone(aliased, "America/New_York")

        assert isinstance(result, ast_module.Alias), f"Expected Alias wrapper preserved, got {type(result).__name__}"
        assert result.alias == "date_from"
        assert isinstance(result.expr, ast_module.Call)
        assert result.expr.name == "assumeNotNull"

    def test_alias_not_added_when_not_present(self):
        """When there's no Alias wrapper, the result should not have one either."""
        from posthog.hogql import ast as ast_module
        from posthog.hogql.transforms.property_types import PropertySwapper

        inner_call = ast_module.Call(name="toDateTime", args=[ast_module.Constant(value="2024-03-01")])
        assume_call = ast_module.Call(name="assumeNotNull", args=[inner_call])

        result = PropertySwapper._ensure_constant_has_timezone(assume_call, "America/New_York")

        assert isinstance(result, ast_module.Call), f"Expected Call, got {type(result).__name__}"
        assert result.name == "assumeNotNull"
