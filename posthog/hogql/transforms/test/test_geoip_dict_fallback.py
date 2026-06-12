from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    flush_persons_and_events,
    materialized,
    snapshot_clickhouse_queries,
)

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import HogQLQueryModifiers
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.base import get_geoip_city_postal_dict
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_PASSWORD


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
        # which is the events properties blob the incident (https://posthog.slack.com/archives/C0B9DDSCTF1) affected.
        sql, _ = self._print_select("SELECT person.properties.$geoip_city_name FROM events")
        assert "dictGetStringOrDefault" not in sql


class TestGeoipDictFallbackExecution(ClickhouseTestMixin, BaseTest):
    """End-to-end: real events, materialized columns, and a real ip_trie dictionary on the test ClickHouse."""

    maxDiff = None
    SOURCE_TABLE = f"{CLICKHOUSE_DATABASE}.geoip_dict_fallback_test_source"

    def setUp(self) -> None:
        super().setUp()
        # Mirror production: city, country code, and IP are materialized; postal code is not.
        for prop in ("$geoip_city_name", "$geoip_country_code", "$ip"):
            self.enterContext(materialized("events", prop))

        # The dictionary is created manually on the real clusters, so the test creates its own miniature version.
        sync_execute(
            f"CREATE TABLE IF NOT EXISTS {self.SOURCE_TABLE} "
            "(prefix String, city_name String, postal_code String) ENGINE = MergeTree() ORDER BY prefix"
        )
        sync_execute(
            f"INSERT INTO {self.SOURCE_TABLE} VALUES "
            "('89.160.20.0/24', 'Linkoping', '582 22'), ('2001:db8::/32', 'Stockholm', '111 20')"
        )
        sync_execute(
            f"""
            CREATE DICTIONARY IF NOT EXISTS {get_geoip_city_postal_dict()} (
                prefix String,
                city_name String,
                postal_code String
            )
            PRIMARY KEY prefix
            SOURCE(CLICKHOUSE(DB '{CLICKHOUSE_DATABASE}' TABLE 'geoip_dict_fallback_test_source' PASSWORD '{CLICKHOUSE_PASSWORD}'))
            LIFETIME(0)
            LAYOUT(IP_TRIE())
            """
        )

        for event, properties in [
            # Stored values always win, even with an IP the dictionary knows.
            (
                "1_stored",
                {
                    "$geoip_city_name": "Sydney",
                    "$geoip_postal_code": "2000",
                    "$geoip_country_code": "AU",
                    "$ip": "89.160.20.129",
                },
            ),
            # Blanked by the incident (https://posthog.slack.com/archives/C0B9DDSCTF1; enrichment ran: country is set),
            # recovered from the IP.
            (
                "2_recovered_v4",
                {"$geoip_city_name": "", "$geoip_postal_code": "", "$geoip_country_code": "SE", "$ip": "89.160.20.129"},
            ),
            ("3_recovered_v6", {"$geoip_city_name": "", "$geoip_country_code": "SE", "$ip": "2001:db8::1"}),
            # Enrichment never ran (no country) — stays blank despite the recoverable IP.
            ("4_unenriched", {"$ip": "89.160.20.129"}),
            # Enrichment ran but there is no IP to recover from — stays blank.
            ("5_no_ip", {"$geoip_city_name": "", "$geoip_postal_code": "", "$geoip_country_code": "SE"}),
        ]:
            _create_event(team=self.team, event=event, distinct_id="user1", properties=properties)
        flush_persons_and_events()

    def tearDown(self) -> None:
        sync_execute(f"DROP DICTIONARY IF EXISTS {get_geoip_city_postal_dict()}")
        sync_execute(f"DROP TABLE IF EXISTS {self.SOURCE_TABLE}")
        super().tearDown()

    def _run(self, fallback: bool) -> list:
        response = execute_hogql_query(
            "SELECT event, properties.$geoip_city_name, properties.$geoip_postal_code FROM events ORDER BY event",
            team=self.team,
            modifiers=HogQLQueryModifiers(useGeoipDictFallback=fallback),
        )
        return response.results

    # Blank representation differs by read path: the materialized city column scrubs '' to NULL, while the
    # non-materialized postal code is a raw JSON extract that returns '' for a present-but-empty key and NULL for a
    # missing one. The fallback must preserve exactly that representation whenever it does not recover a value.

    @snapshot_clickhouse_queries
    def test_fallback_recovers_blanked_values(self) -> None:
        assert self._run(fallback=True) == [
            ("1_stored", "Sydney", "2000"),
            ("2_recovered_v4", "Linkoping", "582 22"),
            ("3_recovered_v6", "Stockholm", "111 20"),
            ("4_unenriched", None, None),
            ("5_no_ip", None, ""),
        ]

    @snapshot_clickhouse_queries
    def test_modifier_off_leaves_values_blank(self) -> None:
        assert self._run(fallback=False) == [
            ("1_stored", "Sydney", "2000"),
            ("2_recovered_v4", None, ""),
            ("3_recovered_v6", None, None),
            ("4_unenriched", None, None),
            ("5_no_ip", None, ""),
        ]
