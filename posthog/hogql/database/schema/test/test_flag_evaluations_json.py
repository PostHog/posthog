from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.property_access_types import RestrictedProperty

from posthog.models.instance_setting import override_instance_config

from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

FLAG_QUERY = (
    "SELECT flag_key, session_id, `$group_0`, request_id, properties.foo, person.properties.plan "
    "FROM posthog.flag_evaluations WHERE properties.bar = 'x'"
)
JSON_TABLE_REF = "FROM flag_evaluations_json AS flag_evaluations"


class TestFlagEvaluationsJsonPrinting(BaseTest):
    def _print(
        self, query: str, *, native_events: bool, reads_json: bool, restricted: set[RestrictedProperty] | None = None
    ) -> str:
        with (
            override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=native_events),
            override_instance_config("FLAG_EVALUATIONS_READS_JSON", reads_json),
            patch("products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled", return_value=True),
        ):
            context = HogQLContext(
                team_id=self.team.pk, team=self.team, enable_select_queries=True, restricted_properties=restricted
            )
            sql, _ = prepare_and_print_ast(parse_select(query), context, "clickhouse")
            return sql

    @parameterized.expand(
        [
            ("legacy_events_switch_off", False, False, False),
            ("legacy_events_switch_on", False, True, False),
            ("native_events_switch_off", True, False, False),
            ("native_events_switch_on", True, True, True),
        ]
    )
    def test_reads_the_json_table_only_for_native_events_with_the_switch_on(
        self, _name: str, native_events: bool, reads_json: bool, expects_json_table: bool
    ):
        sql = self._print(FLAG_QUERY, native_events=native_events, reads_json=reads_json)

        assert (JSON_TABLE_REF in sql) == expects_json_table
        assert ("FROM flag_evaluations WHERE" in sql) != expects_json_table

    def test_switch_off_prints_the_same_sql_on_native_events_as_before_the_switch_existed(self):
        sql = self._print(FLAG_QUERY, native_events=True, reads_json=False)

        assert "flag_evaluations.session_id AS session_id" in sql
        assert "JSONExtractRaw(flag_evaluations.properties" in sql

    def test_json_path_reads_declared_paths_and_typed_subcolumns(self):
        sql = self._print(FLAG_QUERY, native_events=True, reads_json=True)

        assert "flag_evaluations.properties.`$session_id` AS session_id" in sql
        assert "flag_evaluations.properties.`$group_0` AS `$group_0`" in sql
        assert "flag_evaluations.flag_key AS flag_key" in sql
        assert "flag_evaluations.request_id AS request_id" in sql
        assert "CAST(flag_evaluations.properties.foo, 'Nullable(String)')" in sql
        assert "CAST(flag_evaluations.person_properties.plan, 'Nullable(String)')" in sql
        assert "JSONExtractRaw" not in sql

    @parameterized.expand([("switch_off", False), ("switch_on", True)])
    def test_flag_call_union_reads_flag_properties_as_the_events_side_does(self, _name: str, reads_json: bool):
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization,
            defaults={"flag_evaluations_mode": FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY},
        )
        with patch("posthog.hogql.database.database.feature_enabled_or_false", return_value=True):
            sql = self._print(
                "SELECT properties.foo, person.properties.plan, $session_id FROM events "
                "WHERE event IN ('$feature_flag_called', '$pageview')",
                native_events=True,
                reads_json=reads_json,
            )

        assert "FROM events_json AS events" in sql
        assert (JSON_TABLE_REF in sql) == reads_json
        assert ("JSONExtractRaw(flag_evaluations.properties" not in sql) == reads_json
        assert ("CAST(flag_evaluations.properties.foo, 'Nullable(String)')" in sql) == reads_json

    @parameterized.expand([("switch_off", False), ("switch_on", True)])
    def test_restricted_person_property_is_dropped_from_the_flag_documents(self, _name: str, reads_json: bool):
        restricted = {RestrictedProperty(name="secret", property_type=PropertyDefinition.Type.PERSON)}

        sql = self._print(
            "SELECT person.properties, properties FROM posthog.flag_evaluations",
            native_events=True,
            reads_json=reads_json,
            restricted=restricted,
        )

        assert sql.count("JSONDropKeys") == 2
        assert sql.count("JSONDropKeysPool(toString(") == (2 if reads_json else 0)
        assert ("if(empty(flag_evaluations.person_properties)" in sql) != reads_json
