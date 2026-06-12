import pytest
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    flush_persons_and_events,
    materialized,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import PersonsOnEventsMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.modifiers import HogQLQueryModifiers
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.base import get_geoip_city_postal_dict
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.transforms.geoip_dict_fallback import geoip_dict_fallback_enabled_for_team

from posthog.clickhouse.client import sync_execute
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_PASSWORD

from products.event_definitions.backend.models.property_definition import PropertyDefinition


class TestGeoipDictFallback(ClickhouseTestMixin, BaseTest):
    maxDiff = None

    def _print_select(
        self,
        select: str,
        teams: str = "*",
        modifiers: HogQLQueryModifiers | None = None,
        restricted_properties: set[tuple[str, int]] | None = None,
        dict_exists: bool = True,
    ) -> tuple[str, HogQLContext]:
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=modifiers if modifiers is not None else HogQLQueryModifiers(),
            restricted_properties=restricted_properties,
        )
        # The dictionary only exists on the test ClickHouse in the execution tests below, so stub its discovery here.
        with (
            override_settings(HOGQL_GEOIP_DICT_FALLBACK_TEAMS=teams),
            patch(
                "posthog.hogql.transforms.geoip_dict_fallback._geoip_dict_exists",
                return_value=dict_exists,
            ),
        ):
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
            ("env empty", "SELECT properties.$geoip_city_name FROM events", ""),
            ("other team only", "SELECT properties.$geoip_city_name FROM events", "99999999"),
            ("unaffected property", "SELECT properties.$browser FROM events", "*"),
            ("person property", "SELECT properties.$geoip_city_name FROM persons", "*"),
            ("nested key", "SELECT properties.$geoip_city_name.x FROM events", "*"),
        ]
    )
    def test_no_fallback(self, _name: str, select: str, teams: str) -> None:
        sql, _ = self._print_select(select, teams=teams)
        assert "dictGetStringOrDefault" not in sql

    def test_fallback_enabled_for_listed_team(self) -> None:
        sql, _ = self._print_select("SELECT properties.$geoip_city_name FROM events", teams=f"99999999, {self.team.pk}")
        assert "dictGetStringOrDefault" in sql

    def test_no_fallback_when_dictionary_missing(self) -> None:
        sql, _ = self._print_select("SELECT properties.$geoip_city_name FROM events", dict_exists=False)
        assert "dictGetStringOrDefault" not in sql

    def test_enabled_helper_requires_real_dictionary(self) -> None:
        # No stub here: the dictionary does not exist on the test ClickHouse, so the runtime discovery says no even
        # though the env var enables the team.
        with override_settings(HOGQL_GEOIP_DICT_FALLBACK_TEAMS="*"):
            assert geoip_dict_fallback_enabled_for_team(self.team.pk) is False

    def test_person_properties_on_events_not_wrapped_under_poe(self) -> None:
        # Under persons-on-events, person properties live on the events table behind a virtual sub-table whose blob
        # field is also named `properties` — it must not get the fallback (person geo is not what the incident blanked).
        sql, _ = self._print_select(
            "SELECT person.properties.$geoip_city_name FROM events",
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )
        assert "dictGetStringOrDefault" not in sql

    @parameterized.expand(
        [
            ("target restricted", "$geoip_city_name"),
            ("ip restricted", "$ip"),
            ("country restricted", "$geoip_country_code"),
        ]
    )
    def test_no_fallback_for_restricted_properties(self, _name: str, restricted_key: str) -> None:
        # Property-level access control resolves restricted reads to NULL; the fallback must not reconstruct them
        # (or read restricted source properties), so it stands down entirely.
        sql, _ = self._print_select(
            "SELECT properties.$geoip_city_name FROM events",
            restricted_properties={(restricted_key, PropertyDefinition.Type.EVENT)},
        )
        assert "dictGetStringOrDefault" not in sql

    def test_fallback_unaffected_by_unrelated_restriction(self) -> None:
        sql, _ = self._print_select(
            "SELECT properties.$geoip_city_name FROM events",
            restricted_properties={("$browser", PropertyDefinition.Type.EVENT)},
        )
        assert "dictGetStringOrDefault" in sql

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

    def test_lookup_functions_render_for_direct_use_when_enabled(self) -> None:
        sql, _ = self._print_select("SELECT lookupGeoipCityName('89.160.20.129') FROM events")
        assert f"dictGetStringOrDefault('{get_geoip_city_postal_dict()}', 'city_name'" in sql

    def test_lookup_functions_rejected_when_fallback_disabled(self) -> None:
        with pytest.raises(QueryError, match="not available"):
            self._print_select("SELECT lookupGeoipCityName('89.160.20.129') FROM events", teams="")

    @parameterized.expand(
        [
            ("target restricted", "$geoip_postal_code"),
            ("ip restricted", "$ip"),
        ]
    )
    def test_lookup_functions_rejected_for_restricted_properties(self, _name: str, restricted_key: str) -> None:
        # Direct calls must enforce the same guard as the transform: otherwise a user denied the geo property could
        # derive it from a readable `$ip`.
        with pytest.raises(QueryError, match="restricted"):
            self._print_select(
                "SELECT lookupGeoipPostalCode(properties.$ip) FROM events",
                restricted_properties={(restricted_key, PropertyDefinition.Type.EVENT)},
            )

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

        # Deliberately NOT a ClickHouse migration: the fallback is temporary (reverted once the backfill completes), so
        # the dictionary was created manually on the cloud clusters rather than rolled out to every install, and this
        # test creates its own miniature version the same way.
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

    def _run(self, teams: str) -> list:
        with override_settings(HOGQL_GEOIP_DICT_FALLBACK_TEAMS=teams):
            response = execute_hogql_query(
                "SELECT event, properties.$geoip_city_name, properties.$geoip_postal_code FROM events ORDER BY event",
                team=self.team,
            )
        return response.results

    def test_enabled_helper_detects_real_dictionary(self) -> None:
        with override_settings(HOGQL_GEOIP_DICT_FALLBACK_TEAMS="*"):
            assert geoip_dict_fallback_enabled_for_team(self.team.pk) is True

    # Blank representation differs by read path: the materialized city column scrubs '' to NULL, while the
    # non-materialized postal code is a raw JSON extract that returns '' for a present-but-empty key and NULL for a
    # missing one. The fallback must preserve exactly that representation whenever it does not recover a value.

    @snapshot_clickhouse_queries
    def test_fallback_recovers_blanked_values(self) -> None:
        assert self._run(teams=str(self.team.pk)) == [
            ("1_stored", "Sydney", "2000"),
            ("2_recovered_v4", "Linkoping", "582 22"),
            ("3_recovered_v6", "Stockholm", "111 20"),
            ("4_unenriched", None, None),
            ("5_no_ip", None, ""),
        ]

    @snapshot_clickhouse_queries
    def test_env_disabled_leaves_values_blank(self) -> None:
        assert self._run(teams="") == [
            ("1_stored", "Sydney", "2000"),
            ("2_recovered_v4", None, ""),
            ("3_recovered_v6", None, None),
            ("4_unenriched", None, None),
            ("5_no_ip", None, ""),
        ]
