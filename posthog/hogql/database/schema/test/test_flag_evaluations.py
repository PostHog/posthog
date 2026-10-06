import json
import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    ElementPropertyFilter,
    EventPropertyFilter,
    GroupPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
    SessionPropertyFilter,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.flag_evaluations import add_events_list_fields_to_flag_evaluations
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

EVENT_PROBE = "from-event-properties"

# The sessions tables join only on a UUIDv7 session id.
SESSION_ID = str(uuid7())

# Compares greater than 9 as a number and less than it as a string, so the assertion tells the two
# apart rather than passing under either.
NUMERIC_PROBE = 10


class TestFlagEvaluationsTable(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.row_uuid = uuid.uuid4()
        self.person_id = uuid.uuid4()
        self.occurred_at = datetime.now(UTC) - timedelta(minutes=5)
        # The nine typed columns are DEFAULT-computed from `properties` on the sharded table, so a
        # producer cannot write them and this insert must not name them.
        sync_execute(
            """
            INSERT INTO writable_flag_evaluations
                (uuid, event, properties, timestamp, team_id, distinct_id, created_at, person_id)
            VALUES
            """,
            [
                (
                    str(self.row_uuid),
                    "$feature_flag_called",
                    json.dumps(
                        {
                            "$feature_flag": "probe-flag",
                            "$feature_flag_response": "variant-x",
                            "$session_id": SESSION_ID,
                            "$feature_flag_request_id": "req-456",
                            "$group_0": "acme",
                            "probe": EVENT_PROBE,
                            "count": NUMERIC_PROBE,
                        }
                    ),
                    self.occurred_at,
                    self.team.pk,
                    "probe-distinct-id",
                    self.occurred_at,
                    str(self.person_id),
                )
            ],
        )

    def _execute(self, columns: str, where: str = ""):
        # settings.DEBUG is False under the test runner, so the org gate fail-closes and prunes the
        # table. test_database.py covers the gate itself; here it only has to be out of the way.
        context = HogQLContext(team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True)
        with patch(
            "products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled",
            return_value=True,
        ):
            return execute_hogql_query(
                f"SELECT {columns} FROM posthog.flag_evaluations WHERE uuid = '{self.row_uuid}'{where}",
                team=self.team,
                context=context,
                pretty=False,
            )

    def _select(self, columns: str, where: str = ""):
        return self._execute(columns, where).results

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
            "flag_key, response, session_id, request_id, `$group_0`, person_id, person.id, properties.probe"
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
                EVENT_PROBE,
            )
        ]

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

    def test_overrides_are_joined_only_when_person_id_is_read(self):
        # The join is the expensive half of the correction; a query that never names the person must
        # not pay for it.
        assert "person_distinct_id_overrides" not in self._execute("flag_key").clickhouse
        assert "person_distinct_id_overrides" in self._execute("person_id").clickhouse

    def test_asterisk_carries_the_corrected_person_and_no_second_person_column(self):
        # Let the stored column into the expansion and it takes the slot `person_id` held, so the SQL
        # editor's default query shifts every later column and shows two person ids that disagree.
        merged_person_id = uuid.uuid4()
        self._override(merged_person_id, version=1)

        response = self._execute("*")
        columns = response.columns or []

        assert "flag_evaluation_person_id" not in columns
        assert response.results[0][columns.index("person_id")] == merged_person_id

    def test_numeric_property_compares_as_a_number(self):
        # Drop this table from any of the property-type dispatches and the read stays a String, so
        # the comparison no longer answers the numeric question.
        PropertyDefinition.objects.create(
            team=self.team,
            name="count",
            property_type="Numeric",
            type=PropertyDefinition.Type.EVENT,
        )

        assert self._select("properties.count > 9") == [(True,)]

    @parameterized.expand(
        [
            ("flag_key", "flag_key", "$feature_flag", "probe-flag"),
            ("response", "response", "$feature_flag_response", "variant-x"),
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

    def test_restricted_property_is_hidden_from_both_read_paths(self):
        # The explicit read lowers to a NULL constant and the blob read is scrubbed by the printer.
        # Both consult the same dispatch, so a table dropped from it leaks through both.
        self._restrict("probe", PropertyDefinition.Type.EVENT)

        assert self._select("properties.probe") == [(None,)]

        blob = json.loads(self._select("properties")[0][0])

        assert "probe" not in blob
        assert blob["$feature_flag"] == "probe-flag"

    @parameterized.expand(
        [
            ("event", EventPropertyFilter(key="probe", value=EVENT_PROBE, operator=PropertyOperator.EXACT), 1),
            (
                "person",
                PersonPropertyFilter(key="email", value="probe@example.com", operator=PropertyOperator.EXACT),
                1,
            ),
            (
                "group",
                GroupPropertyFilter(
                    key="industry", value="software", operator=PropertyOperator.EXACT, group_type_index=0
                ),
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
        ]
    )
    def test_events_shaped_table_reads_every_events_list_field(self, _name: str, prop, expected_rows: int):
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
