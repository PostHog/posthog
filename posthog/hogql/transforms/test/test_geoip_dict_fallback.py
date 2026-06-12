from posthog.test.base import BaseTest, ClickhouseTestMixin, materialized

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import HogQLQueryModifiers
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.base import get_geoip_city_postal_dict
from posthog.hogql.printer.utils import prepare_and_print_ast


class TestGeoipDictFallback(ClickhouseTestMixin, BaseTest):
    maxDiff = None

    def _print_select(self, select: str, fallback: bool = True) -> tuple[str, HogQLContext]:
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=HogQLQueryModifiers(useGeoipDictFallback=fallback),
        )
        query, _ = prepare_and_print_ast(parse_select(select), context, "clickhouse")
        return query, context

    @parameterized.expand(
        [
            ("$geoip_city_name", "city_name"),
            ("$geoip_postal_code", "postal_code"),
        ]
    )
    def test_fallback_wraps_affected_event_properties(self, property_name: str, dict_attribute: str) -> None:
        sql, context = self._print_select(f"SELECT properties.{property_name} FROM events")
        assert f"dictGetStringOrDefault('{get_geoip_city_postal_dict()}', '{dict_attribute}'" in sql
        assert "toIPv6OrDefault" in sql
        # The recovery is guarded on enrichment having run, so never-enriched rows stay blank. The property keys print
        # as bound parameters, so look for them in the context values rather than the SQL text.
        assert "$geoip_country_code" in context.values.values()
        assert "$ip" in context.values.values()

    @parameterized.expand(
        [
            ("modifier off", "SELECT properties.$geoip_city_name FROM events", False),
            ("unaffected property", "SELECT properties.$browser FROM events", True),
            ("person property", "SELECT properties.$geoip_city_name FROM persons", True),
            ("nested key", "SELECT properties.$geoip_city_name.x FROM events", True),
        ]
    )
    def test_no_fallback(self, _name: str, select: str, fallback: bool) -> None:
        sql, _ = self._print_select(select, fallback=fallback)
        assert "dictGetStringOrDefault" not in sql

    def test_fallback_applies_in_where_clause(self) -> None:
        sql, _ = self._print_select("SELECT count() FROM events WHERE properties.$geoip_city_name = 'London'")
        assert f"dictGetStringOrDefault('{get_geoip_city_postal_dict()}', 'city_name'" in sql

    def test_fallback_reads_materialized_columns(self) -> None:
        with (
            materialized("events", "$geoip_city_name"),
            materialized("events", "$geoip_country_code"),
            materialized("events", "$ip"),
        ):
            sql, _ = self._print_select("SELECT properties.$geoip_city_name FROM events")
        assert "dictGetStringOrDefault" in sql
        # All three reads in the fallback expression resolve to their materialized columns, not JSON extracts.
        assert "mat_$geoip_city_name" in sql
        assert "mat_$geoip_country_code" in sql
        assert "mat_$ip" in sql
        assert "JSONExtract" not in sql

    def test_lookup_functions_render_for_direct_use(self) -> None:
        sql, _ = self._print_select("SELECT lookupGeoipCityName('89.160.20.129') FROM events", fallback=False)
        assert f"dictGetStringOrDefault('{get_geoip_city_postal_dict()}', 'city_name'" in sql

    @parameterized.expand(
        [
            (
                "subquery",
                "SELECT city FROM (SELECT properties.$geoip_city_name AS city FROM events) GROUP BY city",
                1,
            ),
            (
                "cte",
                "WITH geo AS (SELECT properties.$geoip_city_name AS city FROM events) SELECT city FROM geo",
                1,
            ),
            (
                "table alias",
                "SELECT e.properties.$geoip_city_name FROM events AS e",
                1,
            ),
            (
                "group by breakdown",
                "SELECT properties.$geoip_city_name AS city, count() FROM events GROUP BY city ORDER BY count() DESC",
                1,
            ),
            (
                "union all",
                "SELECT properties.$geoip_city_name FROM events UNION ALL SELECT properties.$geoip_city_name FROM events",
                2,
            ),
            (
                "select and where both wrapped",
                "SELECT properties.$geoip_city_name FROM events WHERE properties.$geoip_city_name != ''",
                2,
            ),
        ]
    )
    def test_fallback_in_complex_query_shapes(self, _name: str, select: str, expected_lookups: int) -> None:
        sql, _ = self._print_select(select)
        assert sql.count("dictGetStringOrDefault") == expected_lookups

    def test_fallback_in_join_only_wraps_the_events_side(self) -> None:
        sql, _ = self._print_select(
            "SELECT e.properties.$geoip_city_name, p.properties.$geoip_city_name "
            "FROM events AS e LEFT JOIN persons AS p ON p.id = e.person_id"
        )
        # The events-side read gets the fallback; the persons-side read of the same property name is left alone.
        assert sql.count("dictGetStringOrDefault") == 1

    def test_person_properties_on_events_not_wrapped(self) -> None:
        # person.properties reads off events resolve to the person_properties blob (or a joined subquery), neither of
        # which is the events properties blob the incident affected.
        sql, _ = self._print_select("SELECT person.properties.$geoip_city_name FROM events")
        assert "dictGetStringOrDefault" not in sql
