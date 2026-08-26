import json
import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel

# The row carries the same key in four blobs with a different value in each, so a field pointed at
# the wrong physical column returns another blob's value instead of merely returning something.
EVENT_PROBE = "from-event-properties"
PERSON_PROBE = "from-person-properties"
GROUP0_PROBE = "from-group0-properties"
GROUP1_PROBE = "from-group1-properties"


class TestFlagEvaluationsTable(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.row_uuid = uuid.uuid4()
        self.person_id = uuid.uuid4()
        occurred_at = datetime.now(UTC) - timedelta(minutes=5)
        # The nine typed columns are DEFAULT-computed from `properties` on the sharded table, so a
        # producer cannot write them and this insert must not name them.
        sync_execute(
            """
            INSERT INTO writable_flag_evaluations
                (uuid, event, properties, timestamp, team_id, distinct_id, created_at, person_id,
                 person_properties, group0_properties, group1_properties)
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
                            "$session_id": "sess-123",
                            "$feature_flag_request_id": "req-456",
                            "$group_0": "acme",
                            "probe": EVENT_PROBE,
                        }
                    ),
                    occurred_at,
                    self.team.pk,
                    "probe-distinct-id",
                    occurred_at,
                    str(self.person_id),
                    json.dumps({"probe": PERSON_PROBE}),
                    json.dumps({"probe": GROUP0_PROBE}),
                    json.dumps({"probe": GROUP1_PROBE}),
                )
            ],
        )

    def _select(self, columns: str):
        # settings.DEBUG is False under the test runner, so the org gate fail-closes and prunes the
        # table. test_database.py covers the gate itself; here it only has to be out of the way.
        context = HogQLContext(team_id=self.team.pk, team=self.team, user=self.user, enable_select_queries=True)
        with patch(
            "products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled",
            return_value=True,
        ):
            return execute_hogql_query(
                f"SELECT {columns} FROM posthog.flag_evaluations WHERE uuid = '{self.row_uuid}'",
                team=self.team,
                context=context,
                pretty=False,
            ).results

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
            "flag_key, response, session_id, request_id, `$group_0`, person_id, person.id, "
            "properties.probe, person.properties.probe, group_0.properties.probe, group_1.properties.probe"
        )

        assert results == [
            (
                "probe-flag",
                "variant-x",
                "sess-123",
                "req-456",
                "acme",
                self.person_id,
                self.person_id,
                EVENT_PROBE,
                PERSON_PROBE,
                GROUP0_PROBE,
                GROUP1_PROBE,
            )
        ]

    @parameterized.expand(
        [
            ("event", PropertyDefinition.Type.EVENT, None, "properties.probe", "person.properties.probe", PERSON_PROBE),
            (
                "person",
                PropertyDefinition.Type.PERSON,
                None,
                "person.properties.probe",
                "properties.probe",
                EVENT_PROBE,
            ),
            (
                "group",
                PropertyDefinition.Type.GROUP,
                0,
                "group_0.properties.probe",
                "group_1.properties.probe",
                GROUP1_PROBE,
            ),
        ]
    )
    def test_restricted_property_is_scrubbed_for_its_own_class_only(
        self,
        _name: str,
        property_type,
        group_type_index: int | None,
        restricted: str,
        untouched: str,
        untouched_value: str,
    ):
        # The blob columns are named like the events table's, so they clear the printer's column-name
        # check; whether they are scrubbed depends on the table type reaching a dispatch branch.
        self._restrict("probe", property_type, group_type_index)

        assert self._select(restricted) == [(None,)]
        assert self._select(untouched) == [(untouched_value,)]

    def test_restricted_key_is_dropped_from_a_whole_blob_read(self):
        self._restrict("probe", PropertyDefinition.Type.EVENT)

        blob = self._select("properties")[0][0]

        assert "probe" not in json.loads(blob)
        assert json.loads(blob)["$feature_flag"] == "probe-flag"
