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

from django.conf import settings
from django.test import override_settings

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.hogql import translate_hogql
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.base import get_geoip_city_postal_dict
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.transforms.geoip_dict_fallback import (
    geoip_dict_fallback_enabled_for_team,
    geoip_dict_fallback_team_in_env,
)

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_PASSWORD

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
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
        # as bound parameters on legacy JSONExtract reads, and as identifiers on JSON subcolumn reads.
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert "properties.`$geoip_country_code`" in sql
            assert "properties.`$ip`" in sql
        else:
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
        # though the env var enables the team. The env-membership half (used for cache keys) stays True regardless:
        # cache keys must depend only on operator config, never on the probe.
        with override_settings(HOGQL_GEOIP_DICT_FALLBACK_TEAMS="*"):
            assert geoip_dict_fallback_enabled_for_team(self.team.pk) is False
            assert geoip_dict_fallback_team_in_env(self.team.pk) is True

    def test_no_fallback_in_non_hogql_fragments(self) -> None:
        # Deletion predicates and legacy filters compile via translate_hogql with within_non_hogql_query=True and
        # splice into DELETE mutations on sharded_events: the matched row set must not depend on env/probe state, and
        # a dictGet inside a mutation would wedge the sticky mutation queue if the dictionary disappears.
        context = HogQLContext(team_id=self.team.pk, within_non_hogql_query=True, enable_select_queries=True)
        with (
            override_settings(HOGQL_GEOIP_DICT_FALLBACK_TEAMS="*"),
            patch("posthog.hogql.transforms.geoip_dict_fallback._geoip_dict_exists", return_value=True),
        ):
            sql = translate_hogql("properties.$geoip_city_name = 'London'", context)
        assert "dictGetStringOrDefault" not in sql

    def test_person_properties_on_events_not_wrapped_under_poe(self) -> None:
        # Under persons-on-events, person properties live on the events table behind a virtual sub-table whose blob
        # field is also named `properties` — it must not get the fallback. The incident blanked person geo too, but
        # recovering it is a separate, harder fix (out of scope here); event-time `$ip` recovery doesn't map to it.
        sql, _ = self._print_select(
            "SELECT person.properties.$geoip_city_name FROM events",
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )
        assert "dictGetStringOrDefault" not in sql

    def test_no_fallback_for_restricted_target_property(self) -> None:
        # Property-level access control resolves the restricted read to NULL; the fallback must not reconstruct it
        # from `$ip`, so it stands down entirely.
        sql, _ = self._print_select(
            "SELECT properties.$geoip_city_name FROM events",
            restricted_properties={("$geoip_city_name", PropertyDefinition.Type.EVENT)},
        )
        assert "dictGetStringOrDefault" not in sql

    @parameterized.expand(
        [
            ("select", "SELECT properties.$geoip_city_name FROM events"),
            ("where", "SELECT count() FROM events WHERE properties.$geoip_city_name = 'London'"),
            ("subquery", "SELECT city FROM (SELECT properties.$geoip_city_name AS city FROM events)"),
            ("cte", "WITH geo AS (SELECT properties.$geoip_city_name AS city FROM events) SELECT city FROM geo"),
        ]
    )
    def test_no_fallback_for_restricted_target_in_any_query_shape(self, _name: str, select: str) -> None:
        sql, _ = self._print_select(select, restricted_properties={("$geoip_city_name", PropertyDefinition.Type.EVENT)})
        assert "dictGetStringOrDefault" not in sql

    def test_restriction_guards_apply_per_property(self) -> None:
        # Restricting one of the two affected properties must not disable recovery of the other: with postal
        # restricted, the city read is still wrapped (exactly one lookup) and the postal read is not.
        sql, _ = self._print_select(
            "SELECT properties.$geoip_city_name, properties.$geoip_postal_code FROM events",
            restricted_properties={("$geoip_postal_code", PropertyDefinition.Type.EVENT)},
        )
        assert sql.count("dictGetStringOrDefault") == 1
        assert f"dictGetStringOrDefault('{get_geoip_city_postal_dict()}', 'city_name'" in sql

    def test_no_fallback_when_both_targets_restricted(self) -> None:
        sql, _ = self._print_select(
            "SELECT properties.$geoip_city_name, properties.$geoip_postal_code FROM events",
            restricted_properties={
                ("$geoip_city_name", PropertyDefinition.Type.EVENT),
                ("$geoip_postal_code", PropertyDefinition.Type.EVENT),
            },
        )
        assert "dictGetStringOrDefault" not in sql

    def test_restricted_country_source_read_is_scrubbed(self) -> None:
        # Sibling of the `$ip` pin below: a restricted `$geoip_country_code` guard read resolves to the restricted
        # constant-NULL substitution (never the real column), so recovery misses rather than probing the value.
        with (
            materialized("events", "$geoip_city_name"),
            materialized("events", "$geoip_country_code"),
            materialized("events", "$ip"),
        ):
            sql, _ = self._print_select(
                "SELECT properties.$geoip_city_name FROM events",
                restricted_properties={("$geoip_country_code", PropertyDefinition.Type.EVENT)},
            )
        assert "dictGetStringOrDefault" in sql
        assert "mat_$geoip_country_code" not in sql

    @parameterized.expand(
        [
            ("ip restricted", "$ip", PropertyDefinition.Type.EVENT),
            ("country restricted", "$geoip_country_code", PropertyDefinition.Type.EVENT),
            ("unrelated restricted", "$browser", PropertyDefinition.Type.EVENT),
            ("person-scoped city", "$geoip_city_name", PropertyDefinition.Type.PERSON),
            ("group-scoped city", "$geoip_city_name", PropertyDefinition.Type.GROUP),
            ("session-scoped city", "$geoip_city_name", PropertyDefinition.Type.SESSION),
        ]
    )
    def test_fallback_unaffected_by_non_target_restrictions(
        self, _name: str, restricted_key: str, property_type: int
    ) -> None:
        # Restricted sources don't disable the rewrite: the restriction layer scrubs those reads to NULL, so for such
        # users recovery quietly misses without exposing them (accepted limitation: restricted `$ip` means no recovery
        # even though the derived property is readable). Unrelated restrictions change nothing, and neither do
        # non-event-scoped restrictions on the target name — this is an events-table read.
        sql, _ = self._print_select(
            "SELECT properties.$geoip_city_name FROM events",
            restricted_properties={(restricted_key, property_type)},
        )
        assert "dictGetStringOrDefault" in sql

    def test_restricted_ip_source_read_is_scrubbed(self) -> None:
        # The accepted limitation pinned: with `$ip` restricted, the injected source read resolves to the restricted
        # constant-NULL substitution (never the real column), so recovery misses rather than reading the raw IP.
        with (
            materialized("events", "$geoip_city_name"),
            materialized("events", "$geoip_country_code"),
            materialized("events", "$ip"),
        ):
            sql, _ = self._print_select(
                "SELECT properties.$geoip_city_name FROM events",
                restricted_properties={("$ip", PropertyDefinition.Type.EVENT)},
            )
        assert "dictGetStringOrDefault" in sql
        assert "mat_$ip" not in sql

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
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert "properties.`$geoip_city_name`" in sql
            assert "properties.`$geoip_country_code`" in sql
            assert "properties.`$ip`" in sql
            assert "mat_$geoip_city_name" not in sql
            assert "mat_$geoip_country_code" not in sql
            assert "mat_$ip" not in sql
        else:
            # All three reads in the fallback expression resolve to their materialized columns, not JSON extracts.
            assert "mat_$geoip_city_name" in sql
            assert "mat_$geoip_country_code" in sql
            assert "mat_$ip" in sql
        assert "JSONExtract" not in sql

    def test_lookup_functions_render_for_direct_use_when_enabled(self) -> None:
        sql, _ = self._print_select("SELECT _lookupGeoipCityName('89.160.20.129') FROM events")
        assert f"dictGetStringOrDefault('{get_geoip_city_postal_dict()}', 'city_name'" in sql

    def test_lookup_functions_rejected_when_fallback_disabled(self) -> None:
        with pytest.raises(QueryError, match="not available"):
            self._print_select("SELECT _lookupGeoipCityName('89.160.20.129') FROM events", teams="")

    # The _lookupGeoip* functions are deliberately NOT property-restriction guarded (see the printer): they are pure
    # functions over GeoLite2, a public IP->geo dataset, so they cannot circumvent property-level access control. The
    # two tests below pin the two halves of that argument.

    @parameterized.expand(
        [
            ("event-scoped target", "$geoip_city_name", PropertyDefinition.Type.EVENT),
            ("person-scoped target", "$geoip_city_name", PropertyDefinition.Type.PERSON),
        ]
    )
    def test_lookup_functions_render_despite_target_restriction(
        self, _name: str, restricted_key: str, property_type: int
    ) -> None:
        # Deriving geo data from an IP the user can already read circumvents nothing — any external geo service gives
        # the same answer — and the restricted *stored* property still reads NULL (enforced at the property read and
        # by the transform's target guard, covered by the end-to-end tests below).
        sql, _ = self._print_select(
            "SELECT _lookupGeoipCityName('89.160.20.129') FROM events",
            restricted_properties={(restricted_key, property_type)},
        )
        assert f"dictGetStringOrDefault('{get_geoip_city_postal_dict()}', 'city_name'" in sql

    def test_lookup_functions_cannot_read_restricted_arguments(self) -> None:
        # The other half of why no guard is needed: a restricted property read in the argument is scrubbed to constant
        # NULL by the restriction layer before the function sees it, so the lookup misses — the function is no oracle
        # for restricted values.
        sql, _ = self._print_select(
            "SELECT _lookupGeoipPostalCode(properties.$ip) FROM events",
            restricted_properties={("$ip", PropertyDefinition.Type.EVENT)},
        )
        assert f"dictGetStringOrDefault('{get_geoip_city_postal_dict()}', 'postal_code'" in sql
        assert "toIPv6OrDefault(coalesce(NULL, ''))" in sql

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

    def _run(self, teams: str, with_user: bool = False) -> list:
        with override_settings(HOGQL_GEOIP_DICT_FALLBACK_TEAMS=teams):
            response = execute_hogql_query(
                "SELECT event, properties.$geoip_city_name, properties.$geoip_postal_code FROM events ORDER BY event",
                team=self.team,
                user=self.user if with_user else None,
            )
        return response.results

    def _restrict(self, property_name: str) -> None:
        # Real property-level access control rows, so restrictions load through the production path (requires the
        # entitlement and a user on the query).
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name=property_name, property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team, property_definition=definition, access_level=PropertyAccessLevel.NONE.value
        )

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

    def test_restricted_target_stays_hidden_end_to_end(self) -> None:
        # With city restricted and the fallback enabled, every city value reads NULL — the stored "Sydney" stays
        # hidden, and the recoverable rows must NOT come back as dictionary-derived cities. Postal is unaffected and
        # still recovers.
        self._restrict("$geoip_city_name")
        assert self._run(teams=str(self.team.pk), with_user=True) == [
            ("1_stored", None, "2000"),
            ("2_recovered_v4", None, "582 22"),
            ("3_recovered_v6", None, "111 20"),
            ("4_unenriched", None, None),
            ("5_no_ip", None, ""),
        ]

    def test_restricted_ip_source_means_no_recovery_end_to_end(self) -> None:
        # The accepted limitation on real data: with `$ip` restricted, stored values stay visible but blanked rows
        # cannot recover (the source read scrubs to NULL, so the dictionary misses).
        self._restrict("$ip")
        assert self._run(teams=str(self.team.pk), with_user=True) == [
            ("1_stored", "Sydney", "2000"),
            ("2_recovered_v4", None, ""),
            ("3_recovered_v6", None, None),
            ("4_unenriched", None, None),
            ("5_no_ip", None, ""),
        ]
