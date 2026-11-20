from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.client.escape import substitute_params
from posthog.models.instance_setting import override_instance_config

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

EVENTS = FlagEvaluationsMode.EVENTS
READ = FlagEvaluationsMode.READ_FLAG_EVALUATIONS
STRICT = FlagEvaluationsMode.READ_FLAG_EVALUATIONS_WITHOUT_EVENTS_FALLBACK
ONLY = FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY

FLAG_CALLS = "FROM events WHERE event = '$feature_flag_called'"
MIXED = "event IN ('$pageview', '$feature_flag_called')"
OLDER_THAN_THE_TABLE = "timestamp >= now() - INTERVAL 200 DAY"


class TestMode2ReadsLikeMode3(BaseTest):
    """An organization on READ_FLAG_EVALUATIONS_WITHOUT_EVENTS_FALLBACK compiles every query to the SQL that
    FLAG_EVALUATIONS_ONLY compiles, or fails with the same error. The modes differ only in what ingestion writes to
    events."""

    def _compile(
        self,
        query: str,
        mode: FlagEvaluationsMode,
        *,
        persons_on_events: PersonsOnEventsMode | None = None,
    ) -> str:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization, defaults={"flag_evaluations_mode": mode}
        )
        with patch("products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled", return_value=True):
            try:
                sql, context = HogQLQueryExecutor(
                    query=query,
                    team=self.team,
                    context=HogQLContext(team_id=self.team.pk, rewrite_flag_calls_to_flag_evaluations=True),
                    modifiers=HogQLQueryModifiers(useNewEventsSchema=False, personsOnEventsMode=persons_on_events),
                    pretty=False,
                ).generate_clickhouse_sql()
            except QueryError as error:
                return f"QueryError: {error}"
        return substitute_params(sql, context.values)

    @parameterized.expand(
        [
            ("without_key_or_date", f"SELECT count() {FLAG_CALLS}"),
            ("range_older_than_the_table", f"SELECT count() {FLAG_CALLS} AND {OLDER_THAN_THE_TABLE}"),
            ("select_star", f"SELECT * {FLAG_CALLS}"),
            ("sample", "SELECT count() FROM events SAMPLE 0.1 WHERE event = '$feature_flag_called'"),
            ("final", "SELECT count() FROM events FINAL WHERE event = '$feature_flag_called'"),
            ("mixed_events", f"SELECT count() FROM events WHERE timestamp > now() - INTERVAL 1 DAY AND {MIXED}"),
            ("person_properties", f"SELECT person.properties.email {FLAG_CALLS}"),
            ("property_equals_empty_string", f"SELECT count() {FLAG_CALLS} AND properties.$browser = ''"),
        ]
    )
    def test_compiles_like_mode_3(self, _name: str, query: str):
        assert self._compile(query, STRICT) == self._compile(query, ONLY)

    @parameterized.expand(
        [
            (mode.name, mode)
            for mode in (
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                PersonsOnEventsMode.DISABLED,
            )
        ]
    )
    def test_person_reads_compile_like_mode_3_under_persons_on_events(
        self, _name: str, persons_on_events: PersonsOnEventsMode
    ):
        for select in ("person_id", "person.properties.email", "person.id"):
            query = f"SELECT {select} {FLAG_CALLS}"
            assert self._compile(query, STRICT, persons_on_events=persons_on_events) == self._compile(
                query, ONLY, persons_on_events=persons_on_events
            )

    def test_swaps_a_scan_that_pins_no_key_or_date(self):
        assert "FROM flag_evaluations" in self._compile(f"SELECT count() {FLAG_CALLS}", STRICT)

    def test_refuses_a_shape_flag_evaluations_cannot_answer(self):
        assert self._compile(f"SELECT * {FLAG_CALLS}", STRICT).startswith("QueryError: Your organization's")

    @parameterized.expand(
        [
            ("without_key_or_date", f"SELECT count() {FLAG_CALLS}"),
            ("select_star", f"SELECT * {FLAG_CALLS}"),
            ("mixed_events", f"SELECT count() FROM events WHERE {MIXED}"),
        ]
    )
    def test_force_events_switch_returns_mode_2_to_events(self, _name: str, query: str):
        with override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", True):
            assert self._compile(query, STRICT) == self._compile(query, EVENTS)

    def test_force_events_switch_leaves_mode_3_on_flag_evaluations(self):
        with override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", True):
            assert "FROM flag_evaluations" in self._compile(f"SELECT count() {FLAG_CALLS}", ONLY)

    def test_mixed_query_reads_flag_evaluations_without_the_union_flag(self):
        assert "FROM flag_evaluations" in self._compile(f"SELECT count() FROM events WHERE {MIXED}", STRICT)

    def test_union_disabled_switch_keeps_mixed_queries_on_events_for_mode_2(self):
        with override_instance_config("FLAG_EVALUATIONS_UNION_DISABLED", True):
            sql = self._compile(f"SELECT count() FROM events WHERE {MIXED}", STRICT)
        assert "flag_evaluations" not in sql

    def test_mode_1_keeps_the_events_fallback(self):
        sql = self._compile(f"SELECT * {FLAG_CALLS}", READ)
        assert not sql.startswith("QueryError") and "FROM flag_evaluations" not in sql
