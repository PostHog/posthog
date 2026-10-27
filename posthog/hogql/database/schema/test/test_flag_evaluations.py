import json
import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehousePropertyFilter,
    ElementPropertyFilter,
    EventPropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    HogQLQueryModifiers,
    PersonPropertyFilter,
    PropertyGroupsMode,
    PropertyOperator,
    SessionPropertyFilter,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.flag_evaluations import add_events_list_fields_to_flag_evaluations
from posthog.hogql.database.schema.util.where_clause_extractor import SESSION_BUFFER_DAYS
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.hogql_queries.events_query_runner import SELECT_STAR_FROM_EVENTS_FIELDS
from posthog.models import PropertyDefinition
from posthog.models.group.util import create_group
from posthog.models.utils import uuid7
from posthog.test.persons import create_group_type_mapping, create_person

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import insert_static_cohort

EVENT_PROBE = "from-event-properties"

# The sessions tables join only on a UUIDv7 session id.
SESSION_ID = str(uuid7())

# Compares greater than 9 as a number and less than it as a string, so the assertion tells the two
# apart rather than passing under either.
NUMERIC_PROBE = 10


# The filter types an events list or a team's test account filters can hold, with the rows each matches.
FILTER_CASES = [
    ("event", EventPropertyFilter(key="probe", value=EVENT_PROBE, operator=PropertyOperator.EXACT), 1),
    (
        "person",
        PersonPropertyFilter(key="email", value="probe@example.com", operator=PropertyOperator.EXACT),
        1,
    ),
    # The stored person properties carry no referrer or UTM values. The channel type is then "Unknown".
    (
        "person_virtual_property",
        PersonPropertyFilter(key="$virt_initial_channel_type", value="Unknown", operator=PropertyOperator.EXACT),
        1,
    ),
    (
        "group",
        GroupPropertyFilter(key="industry", value="software", operator=PropertyOperator.EXACT, group_type_index=0),
        1,
    ),
    (
        "session",
        SessionPropertyFilter(
            key="$entry_current_url", value="https://example.com/pricing", operator=PropertyOperator.EXACT
        ),
        1,
    ),
    ("element_href", ElementPropertyFilter(key="href", value="/buy", operator=PropertyOperator.EXACT), 0),
    ("element_text", ElementPropertyFilter(key="text", value="Buy", operator=PropertyOperator.EXACT), 0),
    (
        "element_tag_name",
        ElementPropertyFilter(key="tag_name", value="button", operator=PropertyOperator.EXACT),
        0,
    ),
    (
        "element_selector",
        ElementPropertyFilter(key="selector", value="button#buy", operator=PropertyOperator.EXACT),
        0,
    ),
    # A HogQL test account filter can read a traffic virtual property. The row stores no user agent. A row with no
    # user agent classifies as a bot.
    ("hogql_virtual_property", HogQLPropertyFilter(key="properties.$virt_is_bot"), 1),
]


class TestFlagEvaluationsTable(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.row_uuid = uuid.uuid4()
        self.person_id = uuid.uuid4()
        self.occurred_at = datetime.now(UTC) - timedelta(minutes=5)
        self._insert_row(
            self.row_uuid,
            {
                "$feature_flag": "probe-flag",
                "$feature_flag_response": "variant-x",
                "$session_id": SESSION_ID,
                "$feature_flag_request_id": "req-456",
                "$group_0": "acme",
                "probe": EVENT_PROBE,
                "count": NUMERIC_PROBE,
            },
        )

    def _insert_row(self, row_uuid: uuid.UUID, properties: dict[str, str | int | None]) -> None:
        # The nine typed columns are DEFAULT-computed from `properties` on the sharded table, so a
        # producer cannot write them and this insert must not name them.
        sync_execute(
            """
            INSERT INTO writable_flag_evaluations
                (uuid, event, properties, timestamp, team_id, distinct_id, created_at, person_id, person_properties)
            VALUES
            """,
            [
                (
                    str(row_uuid),
                    "$feature_flag_called",
                    json.dumps(properties),
                    self.occurred_at,
                    self.team.pk,
                    "probe-distinct-id",
                    self.occurred_at,
                    str(self.person_id),
                    json.dumps({"email": "probe@example.com", "plan": "free", "age": NUMERIC_PROBE}),
                )
            ],
        )

    def _execute(
        self,
        columns: str,
        where: str = "",
        modifiers: HogQLQueryModifiers | None = None,
        source: str = "posthog.flag_evaluations",
        *,
        row_uuids: tuple[uuid.UUID, ...] = (),
        placeholders: dict[str, ast.Expr] | None = None,
    ):
        uuids = ", ".join(f"'{row_uuid}'" for row_uuid in row_uuids or (self.row_uuid,))
        # settings.DEBUG is False under the test runner, so the org gate fail-closes and prunes the
        # table. test_database.py covers the gate itself; here it only has to be out of the way.
        context = HogQLContext(team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True)
        with patch(
            "products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled",
            return_value=True,
        ):
            return execute_hogql_query(
                f"SELECT {columns} FROM {source} WHERE uuid IN ({uuids}){where}",
                team=self.team,
                placeholders=placeholders,
                context=context,
                modifiers=modifiers,
                pretty=False,
            )

    def _select(
        self,
        columns: str,
        where: str = "",
        *,
        row_uuids: tuple[uuid.UUID, ...] = (),
        placeholders: dict[str, ast.Expr] | None = None,
    ):
        return self._execute(columns, where, row_uuids=row_uuids, placeholders=placeholders).results

    def _override(self, person_id: uuid.UUID, version: int, is_deleted: bool = False) -> None:
        sync_execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version, is_deleted) VALUES",
            [(self.team.pk, "probe-distinct-id", str(person_id), version, int(is_deleted))],
        )

    def _restrict(self, name: str, property_type, group_type_index: int | None = None) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team,
            name=name,
            property_type="String",
            type=property_type,
            group_type_index=group_type_index,
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            access_level=PropertyAccessLevel.NONE.value,
        )

    def test_every_field_reads_its_own_physical_column(self):
        results = self._select(
            "flag_key, response, session_id, request_id, `$group_0`, person_id, person.id, person_mode, properties.probe"
        )

        assert results == [
            (
                "probe-flag",
                "variant-x",
                SESSION_ID,
                "req-456",
                "acme",
                self.person_id,
                self.person_id,
                "full",
                EVENT_PROBE,
            )
        ]

    def test_shards_compute_the_property_group_maps_on_insert(self):
        row_uuid = uuid.uuid4()
        sync_execute(
            """
            INSERT INTO writable_flag_evaluations
                (uuid, event, properties, person_properties, timestamp, team_id, distinct_id)
            VALUES
            """,
            [
                (
                    str(row_uuid),
                    "$feature_flag_called",
                    json.dumps({"quote": 'a"b', "nulled": None, "$lib": "web", "token": "t", "keep": "yes"}),
                    json.dumps({"email": "a@example.com", "$creator_event_uuid": "x"}),
                    self.occurred_at,
                    self.team.pk,
                    "probe-distinct-id",
                )
            ],
        )

        rows = sync_execute(
            "SELECT properties_group_custom, person_properties_map_custom FROM flag_evaluations WHERE uuid = %(uuid)s",
            {"uuid": str(row_uuid)},
        )

        assert rows == [({"quote": 'a"b', "keep": "yes"}, {"email": "a@example.com"})]

    def test_custom_property_filter_reads_the_property_group_map_for_an_ordinary_value(self):
        where = f" AND properties.probe = '{EVENT_PROBE}'"
        json_read = self._execute(
            "properties.probe", where, modifiers=HogQLQueryModifiers(propertyGroupsMode=PropertyGroupsMode.DISABLED)
        )
        map_read = self._execute(
            "properties.probe", where, modifiers=HogQLQueryModifiers(propertyGroupsMode=PropertyGroupsMode.OPTIMIZED)
        )

        # A read that falls back to the JSON returns the same rows. Only the printed SQL shows whether the
        # filter reads the map. Only a map read can use the bloom filter indexes.
        assert "equals(flag_evaluations.properties_group_custom[" in (map_read.clickhouse or "")
        assert "properties_group_custom" not in (json_read.clickhouse or "")
        assert map_read.results == json_read.results == [(EVENT_PROBE,)]

    @parameterized.expand(
        [
            ("json_null", {"$feature_flag_response": None}),
            ("missing", {}),
            ("empty_string", {"$feature_flag_response": ""}),
            ("null_string", {"$feature_flag_response": "null"}),
        ]
    )
    def test_null_or_missing_response_reads_and_filters_as_null(
        self, _name: str, response_property: dict[str, str | None]
    ):
        row_uuid = uuid.uuid4()
        self._insert_row(row_uuid, {"$feature_flag": "probe-flag", **response_property})
        is_set, is_not_set = (
            property_to_expr(DataWarehousePropertyFilter(key="response", operator=operator), self.team)
            for operator in (PropertyOperator.IS_SET, PropertyOperator.IS_NOT_SET)
        )

        both_rows = (row_uuid, self.row_uuid)

        assert self._select("response", row_uuids=(row_uuid,)) == [(None,)]
        assert self._select("uuid", " AND {filter}", row_uuids=both_rows, placeholders={"filter": is_not_set}) == [
            (row_uuid,)
        ]
        assert self._select("uuid", " AND {filter}", row_uuids=both_rows, placeholders={"filter": is_set}) == [
            (self.row_uuid,)
        ]
        assert self._select("uuid", " AND response != 'variant-x'", row_uuids=(row_uuid,)) == [(row_uuid,)]

    def test_person_id_follows_a_later_merge(self):
        # Ingestion never rewrites the person on the row, so only the read can correct it. Drop the
        # override join and `uniq(person_id)` counts the pre-merge and the post-merge person as two
        # humans. The case where no override exists is covered by the test above, which runs with no
        # rows in the overrides table.
        merged_person_id = uuid.uuid4()
        self._override(merged_person_id, version=1)

        assert self._select("person_id, person.id") == [(merged_person_id, merged_person_id)]

    def test_person_id_follows_the_latest_override_version(self):
        # A distinct_id collects one override row per merge, so the read has to pick the highest version.
        # Point the join at `raw_person_distinct_id_overrides` instead of the deduplicating view and the
        # row comes back once per override, which is also how a fan-out in the join would show up.
        merged_person_id = uuid.uuid4()
        self._override(uuid.uuid4(), version=1)
        self._override(merged_person_id, version=2)

        assert self._select("person_id, person.id") == [(merged_person_id, merged_person_id)]

    def test_deleted_override_falls_back_to_the_stored_person(self):
        # A merge that is undone writes a tombstone rather than removing the row. Drop the `is_deleted`
        # handling from the read and the evaluation stays attributed to a person it no longer belongs to.
        self._override(uuid.uuid4(), version=1)
        self._override(uuid.uuid4(), version=2, is_deleted=True)

        assert self._select("person_id, person.id") == [(self.person_id, self.person_id)]

    @parameterized.expand(
        [
            ("no_person", "flag_key", False),
            ("person_id", "person_id", True),
            ("person_dot_id", "person.id", True),
            ("person_properties", "person.properties.email", False),
        ]
    )
    def test_query_joins_only_the_tables_its_person_fields_need(self, _name: str, columns: str, joins_overrides: bool):
        # The overrides join is the expensive half of the correction. A persons join does not fit in memory on
        # the largest teams. A test account filter on a person property must therefore read the stored properties.
        clickhouse = self._execute(columns).clickhouse

        assert ("person_distinct_id_overrides" in clickhouse) == joins_overrides
        assert "FROM person " not in clickhouse

    def test_asterisk_carries_the_corrected_person_and_no_second_person_column(self):
        # Let the stored column into the expansion and it takes the slot `person_id` held, so the SQL
        # editor's default query shifts every later column and shows two person ids that disagree.
        merged_person_id = uuid.uuid4()
        self._override(merged_person_id, version=1)

        response = self._execute("*")
        columns = response.columns or []

        assert "flag_evaluation_person_id" not in columns
        assert "flag_evaluation_response" not in columns
        assert response.results[0][columns.index("person_id")] == merged_person_id
        # The fields copied from events exist only so that filters resolve. They must not reach the expansion.
        assert not [column for column in columns if column.startswith(("$virt_", "elements_chain", "$session_id"))]

    def test_catalog_lists_response_as_nullable(self):
        # Schema discovery reads the declared nullability, not the expression's type.
        with patch(
            "products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled",
            return_value=True,
        ):
            results = execute_hogql_query(
                "SELECT column_name, is_nullable FROM system.information_schema.columns "
                "WHERE table_name = 'posthog.flag_evaluations' AND column_name IN ('response', 'flag_key')",
                team=self.team,
                user=self.user,
            ).results

        assert {name: bool(nullable) for name, nullable in results or []} == {"response": True, "flag_key": False}

    @parameterized.expand(
        [
            ("event", "properties", "count", PropertyDefinition.Type.EVENT),
            ("person", "person.properties", "age", PropertyDefinition.Type.PERSON),
        ]
    )
    def test_numeric_property_compares_as_a_number(self, _name: str, blob_field: str, name: str, property_type):
        # Drop this table from any of the property-type dispatches and the read stays a String, so
        # the comparison no longer answers the numeric question.
        PropertyDefinition.objects.create(
            team=self.team,
            name=name,
            property_type="Numeric",
            type=property_type,
        )

        assert self._select(f"{blob_field}.{name} > 9") == [(True,)]

    @parameterized.expand(
        [
            ("flag_key", "flag_key", "$feature_flag", "probe-flag"),
            ("response", "response", "$feature_flag_response", "variant-x"),
            ("raw_response", "flag_evaluation_response", "$feature_flag_response", "variant-x"),
            ("session_id", "session_id", "$session_id", SESSION_ID),
            ("request_id", "request_id", "$feature_flag_request_id", "req-456"),
            ("group_key", "`$group_0`", "$group_0", "acme"),
        ]
    )
    def test_column_copying_a_restricted_property_reads_and_filters_as_null(
        self, _name: str, column: str, source_property: str, stored_value: str
    ):
        # These columns hold a second copy of the property, so masking the property paths alone leaves the
        # value readable here. The filter matters as much as the read: an unmasked column narrows a value
        # down through which rows come back, without ever selecting it.
        self._restrict(source_property, PropertyDefinition.Type.EVENT)

        assert self._select(column) == [(None,)]
        assert self._select("uuid", where=f" AND {column} = '{stored_value}'") == []
        # A masked read is a SQL NULL. `NULL != 'x'` and `NULL NOT IN (...)` evaluate to NULL too.
        # ClickHouse's WHERE treats NULL as false unless the printer wraps the comparison in `ifNull(...)`.
        # The row must still come back on a negated comparison, matching the equivalent `properties.<key>` read.
        assert self._select("uuid", where=f" AND {column} != '{stored_value}'") == [(self.row_uuid,)]
        assert self._select("uuid", where=f" AND {column} NOT IN ('{stored_value}')") == [(self.row_uuid,)]

    @parameterized.expand(
        [
            (f"{kind}_{read}", blob_field, restricted, stored_value, property_type, unrestricted, mode)
            for kind, blob_field, restricted, stored_value, property_type, unrestricted in [
                ("event", "properties", "probe", EVENT_PROBE, PropertyDefinition.Type.EVENT, "$feature_flag"),
                ("person", "person.properties", "email", "probe@example.com", PropertyDefinition.Type.PERSON, "plan"),
            ]
            for read, mode in [("json", PropertyGroupsMode.DISABLED), ("map", PropertyGroupsMode.OPTIMIZED)]
        ]
    )
    def test_restricted_property_is_hidden_from_both_read_paths(
        self,
        _name: str,
        blob_field: str,
        restricted: str,
        stored_value: str,
        property_type,
        unrestricted: str,
        mode: PropertyGroupsMode,
    ):
        # The explicit read lowers to a NULL constant and the blob read is scrubbed by the printer.
        # Both consult the same dispatch, so a table dropped from it leaks through both.
        # A filter that reads the map would reveal the value through the rows it returns.
        self._restrict(restricted, property_type)
        modifiers = HogQLQueryModifiers(propertyGroupsMode=mode)

        assert self._execute(f"{blob_field}.{restricted}", modifiers=modifiers).results == [(None,)]
        assert self._execute("uuid", f" AND {blob_field}.{restricted} = '{stored_value}'", modifiers).results == []

        blob = json.loads(self._execute(blob_field, modifiers=modifiers).results[0][0])

        assert restricted not in blob
        assert unrestricted in blob

    @parameterized.expand(
        [(name, prop, expected_rows, False) for name, prop, expected_rows in FILTER_CASES]
        # The events list reads `person` through a persons join instead of the stored properties.
        + [
            (f"{name}_events_list", prop, expected_rows, True)
            for name, prop, expected_rows in FILTER_CASES
            if name == "person"
        ]
    )
    def test_filter_resolves_with_and_without_the_events_list_fields(
        self, _name: str, prop, expected_rows: int, events_list_fields: bool
    ):
        # Insights read the table without the events list fields. A test account filter of any type must resolve
        # there too, or every flag calls insight that filters out test accounts fails.
        create_person(team=self.team, uuid=str(self.person_id), properties={"email": "probe@example.com"})
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group(team_id=self.team.pk, group_type_index=0, group_key="acme", properties={"industry": "software"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="probe-distinct-id",
            timestamp=self.occurred_at,
            properties={"$session_id": SESSION_ID, "$current_url": "https://example.com/pricing"},
        )
        flush_persons_and_events()

        with patch(
            "products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled",
            return_value=True,
        ):
            database = Database.create_for(team=self.team)
            if events_list_fields:
                add_events_list_fields_to_flag_evaluations(database)
            response = execute_hogql_query(
                f"SELECT {', '.join(SELECT_STAR_FROM_EVENTS_FIELDS)} FROM posthog.flag_evaluations AS flag_evaluations "
                "WHERE uuid = {row_uuid} AND {filter}",
                team=self.team,
                placeholders={
                    "row_uuid": ast.Constant(value=self.row_uuid),
                    "filter": property_to_expr(prop, self.team),
                },
                context=HogQLContext(
                    team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True, database=database
                ),
            )

        assert len(response.results) == expected_rows

    def test_cohort_filter_resolves_against_the_person_id_expression(self):
        # A test account filter can exclude a cohort, which compiles to `person_id NOT IN COHORT`. On this table
        # `person_id` is the override-corrected expression, not a stored column.
        cohort = Cohort.objects.create(team=self.team, is_static=True)
        insert_static_cohort([self.person_id], cohort.pk, team_id=self.team.pk)

        assert self._select("uuid", where=f" AND person_id IN COHORT {cohort.pk}") == [(self.row_uuid,)]
        assert self._select("uuid", where=f" AND person_id NOT IN COHORT {cohort.pk}") == []

    @parameterized.expand(
        [
            ("unaliased", "posthog.flag_evaluations", "", True),
            ("events_list_alias", "posthog.flag_evaluations AS flag_evaluations", "", True),
            # Cloned into the key subquery, a group field resolves the same groups join again and recurses.
            (
                "qualified_group_filter",
                "posthog.flag_evaluations",
                " AND posthog.flag_evaluations.group_0.properties.industry = 'software'",
                False,
            ),
        ]
    )
    def test_group_join_reads_only_the_groups_of_the_matched_rows(
        self, _name: str, source: str, where: str, key_bound: bool
    ):
        # Without the key bound, the groups subquery reads every group of the type that the team has.
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group(team_id=self.team.pk, group_type_index=0, group_key="acme", properties={"industry": "software"})

        response = self._execute(
            "group_0.properties.industry", where=f"{where} AND timestamp >= now() - INTERVAL 1 DAY", source=source
        )

        assert ("in(key," in response.clickhouse) == key_bound
        assert response.results == [("software",)]

    @parameterized.expand(
        [
            (
                "group_of_joined_table",
                "SELECT fe.group_0.properties.industry FROM events "
                "JOIN posthog.flag_evaluations AS fe ON fe.distinct_id = events.distinct_id "
                "WHERE events.timestamp >= now() - INTERVAL 1 DAY",
                False,
            ),
            (
                "where_references_joined_table",
                "SELECT flag_evaluations.group_0.properties.industry FROM posthog.flag_evaluations AS flag_evaluations "
                "JOIN events AS e ON e.distinct_id = flag_evaluations.distinct_id "
                "WHERE flag_evaluations.timestamp >= now() - INTERVAL 1 DAY AND e.event = '$pageview'",
                False,
            ),
            (
                "where_names_only_the_outer_table",
                "SELECT flag_evaluations.group_0.properties.industry FROM posthog.flag_evaluations AS flag_evaluations "
                "JOIN events AS e ON e.distinct_id = flag_evaluations.distinct_id "
                "WHERE flag_evaluations.timestamp >= now() - INTERVAL 1 DAY",
                True,
            ),
        ]
    )
    def test_group_join_with_an_explicit_join_reads_the_groups_of_the_right_rows(
        self, _name: str, query: str, key_bound: bool
    ):
        # The outer WHERE bounds only the outer table's rows. It can also name the joined table. A key bound is
        # correct only for a group of the outer table and a WHERE that names no other table.
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group(team_id=self.team.pk, group_type_index=0, group_key="acme", properties={"industry": "software"})
        _create_event(team=self.team, event="$pageview", distinct_id="probe-distinct-id", timestamp=self.occurred_at)
        flush_persons_and_events()

        with patch(
            "products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled",
            return_value=True,
        ):
            response = execute_hogql_query(
                query,
                team=self.team,
                context=HogQLContext(team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True),
                pretty=False,
            )

        assert response.clickhouse is not None
        assert ("in(key," in response.clickhouse) == key_bound
        assert response.results == [("software",)]

    def test_session_join_reads_only_sessions_near_the_query_date_range(self):
        # Without the date bound, the sessions subquery aggregates every session the team has.
        clickhouse = self._execute(
            "session.$entry_current_url", where=" AND timestamp >= now() - INTERVAL 1 DAY"
        ).clickhouse

        assert f"toIntervalDay({SESSION_BUFFER_DAYS})" in clickhouse
