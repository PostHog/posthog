"""
Tests for created_at filtering of group fields based on GroupTypeMapping creation time.
"""

from datetime import UTC, datetime

from posthog.test.base import APIBaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models import GroupTypeMapping


class TestGroupKeyFiltering(APIBaseTest):
    """Test that $group_N fields are filtered based on GroupTypeMapping.created_at"""

    def setUp(self):
        super().setUp()
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

    def test_group_field_with_mapping_and_created_at(self):
        """Test that $group_0 gets filtering when GroupTypeMapping exists with created_at"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2023, 1, 15, 12, 0, 0, tzinfo=UTC),
        )
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

        query = "SELECT $group_0 FROM events"
        parsed = parse_select(query)

        sql, _ = prepare_and_print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn(
            "SELECT if(less(toTimeZone(events.timestamp, %(hogql_val_0)s), %(hogql_val_1)s), %(hogql_val_2)s, events.`$group_0`) AS `$group_0` FROM events WHERE equals(events.team_id,",
            sql,
        )

    def test_group_field_without_mapping(self):
        """Test that $group_0 falls back when no GroupTypeMapping exists"""
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

        query = "SELECT $group_0 FROM events"
        parsed = parse_select(query)

        sql, _ = prepare_and_print_ast(parsed, context=self.context, dialect="clickhouse")

        # Should return an empty string constant (parameterized)
        self.assertIn("SELECT events.`$group_0` AS `$group_0` FROM events", sql)

    def test_multiple_group_fields(self):
        """Test filtering with multiple group type mappings"""
        # Create mappings for groups 0 and 1
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2023, 1, 15, 12, 0, 0, tzinfo=UTC),
        )
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="team",
            group_type_index=1,
            created_at=datetime(2023, 2, 1, 10, 0, 0, tzinfo=UTC),
        )
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

        # Parse a query that references multiple group fields
        query = "SELECT $group_0, $group_1, $group_2 FROM events"
        parsed = parse_select(query)

        sql, _ = prepare_and_print_ast(parsed, context=self.context, dialect="clickhouse")

        # Should have conditional logic for groups 0 and 1, empty string for group 2
        self.assertIn("if(less(toTimeZone(events.timestamp,", sql)
        self.assertIn("events.`$group_0`) AS `$group_0`", sql)
        self.assertIn("events.`$group_1`) AS `$group_1`", sql)
        self.assertIn("events.`$group_2` AS `$group_2`", sql)

    def test_group_field_in_where_clause(self):
        """Test that group filtering works in WHERE clauses"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2023, 1, 15, 12, 0, 0, tzinfo=UTC),
        )
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

        query = "SELECT event FROM events WHERE $group_0 = 'acme'"
        parsed = parse_select(query)

        sql, _ = prepare_and_print_ast(parsed, context=self.context, dialect="clickhouse")

        # Should use the conditional logic in WHERE clause
        self.assertIn("equals(if(less(toTimeZone(events.timestamp,", sql)
        self.assertIn("events.`$group_0`), %(hogql_val_", sql)

    def test_group_join_with_filtering(self):
        """Test that group_1.properties access includes filtering for $group_1"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="team",
            group_type_index=1,
            created_at=datetime(2023, 2, 1, 10, 0, 0, tzinfo=UTC),
        )
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

        query = "SELECT group_1.properties FROM events"
        parsed = parse_select(query)

        sql, _ = prepare_and_print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn("ON equals(if(less(toTimeZone(events.timestamp,", sql)
        self.assertIn("events.`$group_1`), events__group_1.key)", sql)

    def test_multiple_group_joins_with_mixed_mappings(self):
        """Test joins to multiple groups with some having filtering and others not"""
        # Create mapping only for group_0
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2023, 1, 15, 12, 0, 0, tzinfo=UTC),
        )
        # No mapping for group_1
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

        query = "SELECT group_0.properties, group_1.properties FROM events"
        parsed = parse_select(query)

        sql, _ = prepare_and_print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn("ON equals(if(less(toTimeZone(events.timestamp,", sql)
        self.assertIn("events.`$group_0`), events__group_0.key)", sql)
        self.assertIn("ON equals(events.`$group_1`, events__group_1.key)", sql)

    def test_non_clickhouse_dialect_no_filtering(self):
        """Test that non-ClickHouse dialects don't get filtering"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2023, 1, 15, 12, 0, 0, tzinfo=UTC),
        )
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

        query = "SELECT $group_0 FROM events"
        parsed = parse_select(query)

        sql, _ = prepare_and_print_ast(parsed, context=self.context, dialect="hogql")

        self.assertIn("SELECT $group_0 FROM", sql)

    def test_group_alias_with_filtering(self):
        """Test that group aliases (e.g., 'company' for $group_0) work with filtering"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2023, 1, 15, 12, 0, 0, tzinfo=UTC),
        )
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

        query = "SELECT company.properties.name FROM events"
        parsed = parse_select(query)

        sql, _ = prepare_and_print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn(
            "ON equals(if(less(toTimeZone(events.timestamp, %(hogql_val_2)s), %(hogql_val_3)s), %(hogql_val_4)s, events.`$group_0`), events__group_0.key)",
            sql,
        )

    def test_group_alias_in_where_clause(self):
        """Test that group aliases work with filtering in WHERE clauses"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2023, 1, 15, 12, 0, 0, tzinfo=UTC),
        )
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

        query = "SELECT event FROM events WHERE company.properties.name = 'acme'"
        parsed = parse_select(query)

        sql, _ = prepare_and_print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn("ON equals(if(less(toTimeZone(events.timestamp,", sql)
        self.assertIn("), %(hogql_val_3)s), %(hogql_val_4)s, events.`$group_0`), events__group_0.key)", sql)
