import json
import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    cleanup_materialized_columns,
    flush_persons_and_events,
)
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    DataWarehousePropertyFilter,
    DateRange,
    ElementPropertyFilter,
    EventPropertyFilter,
    GroupPropertyFilter,
    HogQLFilters,
    HogQLPropertyFilter,
    HogQLQueryModifiers,
    HogQLQueryResponse,
    PersonPropertyFilter,
    PersonsOnEventsMode,
    PropertyGroupsMode,
    PropertyOperator,
    SessionPropertyFilter,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.flag_evaluations import add_events_list_fields_to_flag_evaluations
from posthog.hogql.database.schema.util.where_clause_extractor import SESSION_BUFFER_DAYS
from posthog.hogql.errors import QueryError
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.utils import is_json_verbatim

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.hogql_queries.events_query_runner import SELECT_STAR_FROM_EVENTS_FIELDS
from posthog.models import PropertyDefinition
from posthog.models.group.util import create_group
from posthog.models.property import TableColumn
from posthog.models.utils import uuid7
from posthog.test.persons import create_group_type_mapping, create_person

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import insert_static_cohort
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

from ee.clickhouse.materialized_columns.columns import materialize

EVENT_PROBE = "from-event-properties"

# The sessions tables join only on a UUIDv7 session id.
SESSION_ID = str(uuid7())

FLAG_CALL_CONJUNCTS = (
    "event = '$feature_flag_called' AND properties.$feature_flag = 'probe-flag' AND timestamp >= now() - INTERVAL 7 DAY"
)
FLAG_CALLS_ON_EVENTS = f"SELECT count() FROM events WHERE {FLAG_CALL_CONJUNCTS}"
PAGEVIEW_CONJUNCTS = "event = '$pageview' AND timestamp >= now() - INTERVAL 7 DAY"

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
                "$window_id": "probe-window",
                "probe": EVENT_PROBE,
                "count": NUMERIC_PROBE,
            },
        )

    def _insert_row(
        self,
        row_uuid: uuid.UUID,
        properties: dict[str, str | int | None],
        person_properties: dict[str, str | int] | None = None,
    ) -> None:
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
                    json.dumps(
                        person_properties
                        if person_properties is not None
                        else {"email": "probe@example.com", "plan": "free", "age": NUMERIC_PROBE}
                    ),
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

    def _query_events(
        self,
        query: str,
        *,
        rewrite: bool = True,
        filters: HogQLFilters | None = None,
        modifiers: HogQLQueryModifiers | None = None,
        mode: FlagEvaluationsMode = FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
    ) -> HogQLQueryResponse:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization, defaults={"flag_evaluations_mode": mode}
        )
        with patch(
            "posthog.hogql.database.database.feature_enabled_or_false",
            side_effect=lambda key, *args, **kwargs: rewrite and key == "hogql-flag-calls-from-flag-evaluations",
        ):
            return execute_hogql_query(query, team=self.team, filters=filters, modifiers=modifiers, pretty=False)

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
            "flag_key, response, session_id, request_id, `$group_0`, goe_0.key, `$window_id`, person_id, person.id, "
            "person_mode, properties.probe"
        )

        assert results == [
            (
                "probe-flag",
                "variant-x",
                SESSION_ID,
                "req-456",
                "acme",
                "acme",
                "probe-window",
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

        assert self._select("person_id, person.id, event_person_id") == [
            (merged_person_id, merged_person_id, self.person_id)
        ]

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
            ("group_key_through_goe", "goe_0.key", "$group_0", "acme"),
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
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            created_at=self.occurred_at - timedelta(days=1),
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
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            created_at=self.occurred_at - timedelta(days=1),
        )
        create_group(team_id=self.team.pk, group_type_index=0, group_key="acme", properties={"industry": "software"})

        response = self._execute(
            "group_0.properties.industry", where=f"{where} AND timestamp >= now() - INTERVAL 1 DAY", source=source
        )

        assert ("in(key," in response.clickhouse) == key_bound
        assert response.results == [("software",)]

    def test_group_join_of_a_swapped_events_scan_reads_only_the_groups_of_the_matched_rows(self):
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            created_at=self.occurred_at - timedelta(days=1),
        )
        create_group(team_id=self.team.pk, group_type_index=0, group_key="acme", properties={"industry": "software"})

        response = self._query_events(f"SELECT group_0.properties.industry FROM events WHERE {FLAG_CALL_CONJUNCTS}")

        assert response.clickhouse is not None
        assert "FROM flag_evaluations" in response.clickhouse
        assert "in(key," in response.clickhouse
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
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            created_at=self.occurred_at - timedelta(days=1),
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

    def test_flag_call_query_on_events_reads_no_flag_evaluations_with_the_flag_off(self):
        assert self._query_events(FLAG_CALLS_ON_EVENTS, rewrite=False).results == [(0,)]

    @parameterized.expand(
        [
            ("unaliased", FLAG_CALLS_ON_EVENTS, [(1,)]),
            (
                "qualified_without_an_alias",
                "SELECT count() FROM events WHERE events.event = '$feature_flag_called' "
                "AND events.properties.$feature_flag = 'probe-flag' AND events.timestamp >= now() - INTERVAL 7 DAY",
                [(1,)],
            ),
            (
                "aliased",
                "SELECT count() FROM events AS e WHERE e.event = '$feature_flag_called' "
                "AND e.properties.$feature_flag = 'probe-flag' AND e.timestamp >= now() - INTERVAL 7 DAY",
                [(1,)],
            ),
            (
                "alias_named_flag_key_read_back",
                "SELECT properties.$feature_flag AS flag_key, count() FROM events "
                f"WHERE {FLAG_CALL_CONJUNCTS} GROUP BY flag_key",
                [("probe-flag", 1)],
            ),
            ("element_column", f"SELECT elements_chain FROM events WHERE {FLAG_CALL_CONJUNCTS}", [("",)]),
            ("subquery_in_from", f"SELECT count() FROM (SELECT uuid FROM events WHERE {FLAG_CALL_CONJUNCTS})", [(1,)]),
            (
                "cte",
                f"WITH calls AS (SELECT uuid FROM events WHERE {FLAG_CALL_CONJUNCTS}) SELECT count() FROM calls",
                [(1,)],
            ),
            (
                "body_of_a_cte_named_events",
                f"WITH events AS (SELECT uuid FROM events WHERE {FLAG_CALL_CONJUNCTS}) SELECT count() FROM events",
                [(1,)],
            ),
            (
                "subquery_in_an_expression",
                f"SELECT count() FROM events WHERE {PAGEVIEW_CONJUNCTS} "
                f"AND distinct_id IN (SELECT distinct_id FROM events WHERE {FLAG_CALL_CONJUNCTS})",
                [(1,)],
            ),
            (
                "union_members",
                f"SELECT 'calls', count() FROM events WHERE {FLAG_CALL_CONJUNCTS} "
                f"UNION ALL SELECT 'pageviews', count() FROM events WHERE {PAGEVIEW_CONJUNCTS}",
                [("calls", 1), ("pageviews", 1)],
            ),
            (
                "filters_placeholder",
                "SELECT count() FROM events WHERE event = '$feature_flag_called' "
                "AND properties.$feature_flag = 'probe-flag' AND {filters}",
                [(1,)],
                HogQLFilters(dateRange=DateRange(date_from="-7d")),
            ),
        ]
    )
    def test_each_select_on_events_reads_flag_evaluations_on_its_own(
        self, _name: str, query: str, expected: list[tuple], filters: HogQLFilters | None = None
    ):
        _create_event(team=self.team, event="$pageview", distinct_id="probe-distinct-id", timestamp=self.occurred_at)
        flush_persons_and_events()

        assert sorted(self._query_events(query, filters=filters).results) == expected

    @parameterized.expand(
        [
            ("window_id", "$window_id"),
            ("event_person_id", "event_person_id"),
            ("pdi", "pdi.person_id"),
            ("group_key", "goe_0.key"),
            ("group_properties", "group_0.properties.industry"),
        ]
    )
    def test_query_reading_an_events_only_name_reads_flag_evaluations(self, _name: str, field: str):
        # pdi is an inner join on distinct_id, as on events.
        create_person(team=self.team, distinct_ids=["probe-distinct-id"])
        self._create_events_only_flag_call()

        results = self._query_events(f"SELECT distinct_id, {field} FROM events WHERE {FLAG_CALL_CONJUNCTS}").results

        assert [row[0] for row in results] == ["probe-distinct-id"]

    @parameterized.expand(
        [
            (
                "event_time_group_properties",
                f"SELECT distinct_id, goe_0.properties FROM events WHERE {FLAG_CALL_CONJUNCTS}",
                "reads something that table doesn't have",
            ),
            ("select_star", f"SELECT * FROM events WHERE {FLAG_CALL_CONJUNCTS}", "selects \\* or COLUMNS"),
            (
                "with_name_that_a_flag_evaluations_column_shadows",
                f"WITH 'all calls' AS flag_key SELECT flag_key FROM events WHERE {FLAG_CALL_CONJUNCTS}",
                "a name in it would read a different column",
            ),
            (
                "columns_inside_an_expression",
                f"SELECT tuple(*COLUMNS('^(created|inserted)_at$')) FROM events WHERE {FLAG_CALL_CONJUNCTS}",
                "a name in it would read a different column",
            ),
            (
                "stored_person_id",
                f"SELECT person_id FROM events WHERE {FLAG_CALL_CONJUNCTS}",
                "a name in it would read a different column",
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            ),
            (
                "person_id_through_distinct_ids",
                f"SELECT person_id FROM events WHERE {FLAG_CALL_CONJUNCTS}",
                "a name in it would read a different column",
                PersonsOnEventsMode.DISABLED,
            ),
            (
                "current_person_properties",
                f"SELECT person.properties.email FROM events WHERE {FLAG_CALL_CONJUNCTS}",
                "a name in it would read a different column",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            ),
        ]
    )
    def test_query_flag_evaluations_cannot_answer_reads_events_until_events_gets_no_flag_calls(
        self,
        _name: str,
        query: str,
        error: str,
        persons_on_events_mode: PersonsOnEventsMode = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
    ):
        modifiers = HogQLQueryModifiers(personsOnEventsMode=persons_on_events_mode)
        mode = FlagEvaluationsMode.READ_FLAG_EVALUATIONS
        assert (
            self._query_events(query, modifiers=modifiers, mode=mode).clickhouse
            == self._query_events(query, rewrite=False, modifiers=modifiers, mode=mode).clickhouse
        )
        with self.assertRaisesRegex(QueryError, error):
            self._query_events(query, modifiers=modifiers)

    @parameterized.expand(
        [
            (
                "select_star",
                "WITH events AS (SELECT event, distinct_id FROM posthog.flag_evaluations) "
                "SELECT * FROM events WHERE event = '$feature_flag_called'",
            ),
            (
                "flag_call_filters",
                "WITH events AS (SELECT uuid, event, properties, timestamp FROM posthog.flag_evaluations) "
                f"SELECT uuid FROM events WHERE {FLAG_CALL_CONJUNCTS}",
            ),
            (
                "root_cte_in_a_union_branch",
                "WITH events AS (SELECT uuid, event, properties, timestamp FROM posthog.flag_evaluations) "
                f"SELECT uuid FROM events WHERE {FLAG_CALL_CONJUNCTS} "
                f"UNION ALL SELECT uuid FROM events WHERE {FLAG_CALL_CONJUNCTS}",
            ),
            (
                "subquery",
                "WITH events AS (SELECT uuid, event, properties, timestamp FROM posthog.flag_evaluations) "
                f"SELECT count() FROM (SELECT uuid FROM events WHERE {FLAG_CALL_CONJUNCTS})",
            ),
            (
                "select_star_excluding_flag_calls",
                "SELECT * FROM events WHERE event != '$feature_flag_called' AND timestamp >= now() - INTERVAL 7 DAY",
            ),
            (
                "select_star_of_flag_calls_and_other_events",
                "SELECT * FROM events WHERE event IN ('$feature_flag_called', '$pageview') "
                "AND timestamp >= now() - INTERVAL 7 DAY",
            ),
        ]
    )
    def test_query_that_does_not_read_only_flag_calls_from_events_is_unchanged_once_events_gets_no_flag_calls(
        self, _name: str, query: str
    ):
        assert self._query_events(query).clickhouse == self._query_events(query, rewrite=False).clickhouse

    @parameterized.expand(
        [
            ("no_lower_bound", "SELECT distinct_id FROM events WHERE event = '$feature_flag_called'"),
            (
                "bound_before_coverage",
                "SELECT distinct_id FROM events WHERE event = '$feature_flag_called' "
                "AND properties.$feature_flag = 'probe-flag' AND timestamp >= now() - INTERVAL 180 DAY",
            ),
        ]
    )
    def test_query_reads_flag_evaluations_without_coverage_once_events_gets_no_flag_calls(self, _name: str, query: str):
        self._create_events_only_flag_call()

        on_events = self._query_events(query, mode=FlagEvaluationsMode.READ_FLAG_EVALUATIONS).results
        on_flag_evaluations = self._query_events(query).results

        assert [row[0] for row in on_events] == ["events-distinct-id"]
        assert [row[0] for row in on_flag_evaluations] == ["probe-distinct-id"]

    def _create_events_only_flag_call(self) -> None:
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="events-distinct-id",
            timestamp=self.occurred_at,
            properties={"$feature_flag": "probe-flag", "$window_id": "probe-window"},
        )
        create_person(team=self.team, distinct_ids=["events-distinct-id"])
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("string", "variant-a"),
            ("escaped_characters", 'say "hi" \\ bye'),
            ("number_as_string", "100"),
            ("number", 100),
            ("boolean", True),
            (
                "quoted_flag_key_read_through_json_extract_string",
                "variant-a",
                'say "hi"',
                "JSONExtractString(properties, '$feature_flag')",
            ),
        ]
    )
    def test_swapped_query_returns_what_events_returns_for_the_same_flag_calls(
        self,
        _name: str,
        response: str | int,
        flag_key: str = "parity-flag",
        flag_key_read: str = "properties.$feature_flag",
    ):
        # Mode 1 writes each flag call to both tables, so the two reads must agree row for row.
        row_uuid = uuid.uuid4()
        properties: dict[str, str | int | None] = {"$feature_flag": flag_key, "$feature_flag_response": response}
        self._insert_row(row_uuid, properties)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="probe-distinct-id",
            timestamp=self.occurred_at,
            properties=properties,
            event_uuid=str(row_uuid),
            person_id=self.person_id,
        )
        # The override is a merge after the call, so each table must correct the person it stored.
        merged_person_id = uuid.uuid4()
        self._override(merged_person_id, version=1)
        flush_persons_and_events()
        query = (
            "SELECT uuid, distinct_id, person_id, properties.$feature_flag_response FROM events "
            f"WHERE event = '$feature_flag_called' AND {flag_key_read} = '{flag_key}' "
            "AND timestamp >= now() - INTERVAL 7 DAY"
        )
        modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS)

        from_events = self._query_events(query, rewrite=False, modifiers=modifiers).results
        swapped = self._query_events(query, modifiers=modifiers)

        assert len(from_events) == 1
        assert from_events[0][2] == merged_person_id
        assert swapped.clickhouse is not None
        assert "FROM flag_evaluations" in swapped.clickhouse
        if (
            settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA
            and isinstance(response, str)
            and not is_json_verbatim(response)
        ):
            # The native-JSON events table decodes JSON escapes in a property value. flag_evaluations returns the
            # escaped text, as the legacy events table does.
            assert [row[:3] for row in swapped.results] == [row[:3] for row in from_events]
            assert from_events[0][3] == response
            assert swapped.results[0][3] == json.dumps(response)[1:-1]
            return
        assert swapped.results == from_events

    def test_group_key_of_a_call_from_before_its_group_type_existed_reads_as_on_events(self):
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="probe-distinct-id",
            timestamp=self.occurred_at,
            properties={"$feature_flag": "probe-flag", "$group_0": "acme"},
            event_uuid=str(self.row_uuid),
        )
        flush_persons_and_events()
        query = f"SELECT `$group_0`, goe_0.key FROM events WHERE {FLAG_CALL_CONJUNCTS}"

        from_events = self._query_events(query, rewrite=False).results

        assert from_events == [("", "acme")]
        assert self._query_events(query).results == from_events

    def test_swapped_prewhere_that_reads_an_overridden_person_id_runs(self):
        response = self._query_events(
            f"SELECT count() FROM events PREWHERE person_id IS NOT NULL WHERE {FLAG_CALL_CONJUNCTS}",
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )

        assert response.results == [(1,)]

    def test_swapped_scan_reads_exception_values_as_an_array(self):
        results = self._query_events(
            f"SELECT count() FROM events WHERE {FLAG_CALL_CONJUNCTS} AND NOT has(properties.$exception_values, 'x')"
        ).results

        assert results == [(1,)]

    @parameterized.expand(
        [
            # The events-only call has the JSON value true as its key. A typed comparison matches it on events.
            ("mode_1", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, True),
            ("mode_2", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, False),
        ]
    )
    def test_flag_key_typed_as_boolean_selects_the_same_calls_with_and_without_the_rewrite(
        self, _name: str, mode: FlagEvaluationsMode, with_events_only_call: bool
    ):
        PropertyDefinition.objects.create(
            team=self.team, name="$feature_flag", property_type="Boolean", type=PropertyDefinition.Type.EVENT
        )
        row_uuid = uuid.uuid4()
        self._insert_row(row_uuid, {"$feature_flag": "true"})
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="probe-distinct-id",
            timestamp=self.occurred_at,
            properties={"$feature_flag": "true"},
            event_uuid=str(row_uuid),
        )
        if with_events_only_call:
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id="events-distinct-id",
                timestamp=self.occurred_at,
                properties={"$feature_flag": True},
            )
        flush_persons_and_events()
        query = (
            "SELECT distinct_id FROM events WHERE event = '$feature_flag_called' "
            "AND properties.$feature_flag = 'TRUE' AND timestamp >= now() - INTERVAL 7 DAY"
        )

        from_events = self._query_events(query, rewrite=False, mode=mode).results

        swapped = self._query_events(query, mode=mode)

        assert len(from_events) == (2 if with_events_only_call else 1)
        assert sorted(swapped.results) == sorted(from_events)
        if mode == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY:
            assert swapped.clickhouse is not None
            assert "FROM flag_evaluations" in swapped.clickhouse

    @parameterized.expand(
        [
            # The legacy events table returns the escaped text, as flag_evaluations does, so neither read matches.
            ("legacy_events", False, 0),
            ("native_json_events", True, 1),
        ]
    )
    def test_filter_on_an_escaped_property_selects_the_same_calls_with_and_without_the_rewrite(
        self, _name: str, use_new_events_schema: bool, expected_count: int
    ):
        row_uuid = uuid.uuid4()
        properties: dict[str, str | int | None] = {"$feature_flag": "probe-flag", "message": 'say "hi"'}
        self._insert_row(row_uuid, properties)
        query = f"SELECT count() FROM events WHERE {FLAG_CALL_CONJUNCTS} AND properties.message = 'say \"hi\"'"

        with override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=use_new_events_schema):
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id="probe-distinct-id",
                timestamp=self.occurred_at,
                properties=properties,
                event_uuid=str(row_uuid),
            )
            flush_persons_and_events()
            from_events = self._query_events(query, rewrite=False, mode=FlagEvaluationsMode.READ_FLAG_EVALUATIONS)
            rewritten = self._query_events(query, mode=FlagEvaluationsMode.READ_FLAG_EVALUATIONS)

        assert from_events.results == [(expected_count,)]
        assert rewritten.results == from_events.results
        assert rewritten.clickhouse is not None
        assert ("FROM flag_evaluations" in rewritten.clickhouse) is not use_new_events_schema

    @parameterized.expand(
        [
            ("no_materialized_column", None, "isNull(properties.$current_url)", True),
            ("materialized_event_property", ("properties", "$current_url"), "isNull(properties.$current_url)", False),
            ("materialized_person_property", ("person_properties", "email"), "isNull(person.properties.email)", False),
            # The pin keeps the flag key away from "" and "null", the values a materialized column reads differently.
            ("materialized_flag_key", ("properties", "$feature_flag"), "isNull(properties.$current_url)", True),
        ]
    )
    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
    def test_property_read_from_a_materialized_column_on_events_keeps_reading_events_in_mode_1(
        self, _name: str, materialized_property: tuple[TableColumn, str] | None, condition: str, swaps: bool
    ):
        if materialized_property is not None:
            table_column, property_name = materialized_property
            materialize("events", property_name, table_column=table_column)
            self.addCleanup(cleanup_materialized_columns)
        for value in ("", "null"):
            row_uuid = uuid.uuid4()
            properties: dict[str, str | int | None] = {"$feature_flag": "parity-flag", "$current_url": value}
            self._insert_row(row_uuid, properties, person_properties={"email": value})
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id="probe-distinct-id",
                timestamp=self.occurred_at,
                properties=properties,
                person_properties={"email": value},
                person_id=self.person_id,
                event_uuid=str(row_uuid),
            )
        flush_persons_and_events()
        query = (
            "SELECT count() FROM events WHERE event = '$feature_flag_called' "
            f"AND properties.$feature_flag = 'parity-flag' AND timestamp >= now() - INTERVAL 7 DAY AND {condition}"
        )
        modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS)
        mode = FlagEvaluationsMode.READ_FLAG_EVALUATIONS

        from_events = self._query_events(query, rewrite=False, modifiers=modifiers, mode=mode)
        rewritten = self._query_events(query, modifiers=modifiers, mode=mode)

        assert rewritten.results == from_events.results
        assert rewritten.clickhouse is not None
        assert ("FROM flag_evaluations" in rewritten.clickhouse) is swaps

    @parameterized.expand(
        [
            ("flag_calls", f"SELECT uuid FROM events WHERE {FLAG_CALL_CONJUNCTS}", "saved_calls"),
            ("view_of_a_flag_call_view", "SELECT uuid FROM inner_calls", "inner_calls"),
            ("pageviews", f"SELECT uuid FROM events WHERE {PAGEVIEW_CONJUNCTS}", None),
            (
                "cte_named_events",
                "WITH events AS (SELECT uuid, event, properties, timestamp FROM posthog.flag_evaluations) "
                f"SELECT uuid FROM events WHERE {FLAG_CALL_CONJUNCTS}",
                None,
            ),
        ]
    )
    def test_view_that_reads_flag_calls_from_events_raises_once_events_gets_no_flag_calls(
        self, _name: str, view_query: str, failing_view: str | None
    ):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="inner_calls",
            query={"query": f"SELECT uuid FROM events WHERE {FLAG_CALL_CONJUNCTS}"},
            columns={"uuid": "String"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team, name="saved_calls", query={"query": view_query}, columns={"uuid": "String"}
        )
        query = "SELECT count() FROM saved_calls"

        # events still gets flag calls on mode 1, so the view's read of events is complete.
        self._query_events(query, mode=FlagEvaluationsMode.READ_FLAG_EVALUATIONS)
        if failing_view is None:
            self._query_events(query)
            return
        with self.assertRaisesRegex(QueryError, f"reads the saved view {failing_view}, which reads them from events"):
            self._query_events(query)

    def test_flag_call_query_on_events_prints_a_read_of_flag_evaluations(self):
        self.assertQueryMatchesSnapshot(self._query_events(FLAG_CALLS_ON_EVENTS).clickhouse)
