"""
Tests for created_at filtering of group fields based on GroupTypeMapping creation time.
"""

from datetime import datetime, UTC

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.test.base import APIBaseTest


class TestGroupKeyFiltering(APIBaseTest):
    """Test that $group_N fields are filtered based on GroupTypeMapping.created_at"""

    def setUp(self):
        super().setUp()
        self.database = create_hogql_database(team=self.team)
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

        query = "SELECT $group_0 FROM events"
        parsed = parse_select(query)

        sql = print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn("if(events.timestamp < '2023-01-15 12:00:00', '', `$group_0`) AS `$group_0`", sql)

    def test_group_field_without_mapping(self):
        """Test that $group_0 returns empty string when no GroupTypeMapping exists"""

        query = "SELECT $group_0 FROM events"
        parsed = parse_select(query)

        sql = print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn("'' AS `$group_0`", sql)

    def test_group_field_with_mapping_no_created_at(self):
        """Test that $group_0 works normally when GroupTypeMapping exists but has no created_at"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=None,
        )

        query = "SELECT $group_0 FROM events"
        parsed = parse_select(query)

        sql = print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn("`$group_0` AS `$group_0`", sql)

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

        # Parse a query that references multiple group fields
        query = "SELECT $group_0, $group_1, $group_2 FROM events"
        parsed = parse_select(query)

        sql = print_ast(parsed, context=self.context, dialect="clickhouse")

        # Should have conditional logic for groups 0 and 1
        self.assertIn("if(events.timestamp < '2023-01-15 12:00:00', '', `$group_0`) AS `$group_0`", sql)
        self.assertIn("if(events.timestamp < '2023-02-01 10:00:00', '', `$group_1`) AS `$group_1`", sql)
        self.assertIn("'' AS `$group_2`", sql)

    def test_group_field_in_where_clause(self):
        """Test that group filtering works in WHERE clauses"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2023, 1, 15, 12, 0, 0, tzinfo=UTC),
        )

        query = "SELECT event FROM events WHERE $group_0 = 'acme'"
        parsed = parse_select(query)

        sql = print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn("equals(if(events.timestamp < '2023-01-15 12:00:00', '', `$group_0`), %(hogql_val_0)s)", sql)

    def test_group_join_with_filtering(self):
        """Test that group_1.properties access includes filtering for $group_1"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="team",
            group_type_index=1,
            created_at=datetime(2023, 2, 1, 10, 0, 0, tzinfo=UTC),
        )

        query = "SELECT group_1.properties FROM events"
        parsed = parse_select(query)

        sql = print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn("ON equals(if(events.timestamp < '2023-02-01 10:00:00', '', `$group_1`)", sql)

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

        query = "SELECT group_0.properties, group_1.properties FROM events"
        parsed = parse_select(query)

        sql = print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn("ON equals(if(events.timestamp < '2023-01-15 12:00:00', '', `$group_0`)", sql)
        self.assertIn("ON equals('', events__group_1.key)", sql)

    def test_non_clickhouse_dialect_no_filtering(self):
        """Test that non-ClickHouse dialects don't get filtering"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2023, 1, 15, 12, 0, 0, tzinfo=UTC),
        )

        query = "SELECT $group_0 FROM events"
        parsed = parse_select(query)

        sql = print_ast(parsed, context=self.context, dialect="hogql")

        self.assertIn("$group_0", sql)
        self.assertNotIn("if(", sql.lower())

    def test_group_alias_with_filtering(self):
        """Test that group aliases (e.g., 'company' for $group_0) work with filtering"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2023, 1, 15, 12, 0, 0, tzinfo=UTC),
        )
        self.database = create_hogql_database(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

        query = "SELECT company.properties.name FROM events"
        parsed = parse_select(query)

        sql = print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn("ON equals(if(events.timestamp < '2023-01-15 12:00:00', '', `$group_0`)", sql)

    def test_group_alias_in_where_clause(self):
        """Test that group aliases work with filtering in WHERE clauses"""
        GroupTypeMapping.objects.create(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2023, 1, 15, 12, 0, 0, tzinfo=UTC),
        )
        self.database = create_hogql_database(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

        query = "SELECT event FROM events WHERE company.properties.name = 'acme'"
        parsed = parse_select(query)

        sql = print_ast(parsed, context=self.context, dialect="clickhouse")

        self.assertIn("ON equals(if(events.timestamp < '2023-01-15 12:00:00', '', `$group_0`)", sql)
