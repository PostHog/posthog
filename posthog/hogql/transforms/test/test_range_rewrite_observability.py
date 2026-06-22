"""Integration coverage for the materialized-range-rewrite observability counter.

These run the real ClickHouse property-resolution transform (not the record_* hooks in isolation) so they pin the
counter to the query shapes that reach it. The accumulator is injected in place of the sampling draw. The dominant
production shape — a numeric/datetime property range filter, which materializes to a string column — must record
"skipped"; before the fix it recorded nothing, which is why the counter never emitted.
"""

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, cleanup_materialized_columns
from unittest.mock import patch

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.schema import HogQLQueryModifiers, MaterializationMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.observability import HogQLTypeObservability
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models import PropertyDefinition

from products.event_definitions.backend.models.property_definition import PropertyType

from ee.clickhouse.materialized_columns.columns import materialize


class TestMaterializedRangeRewriteObservability(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cleanup_materialized_columns()
        self.addCleanup(cleanup_materialized_columns)

    def _range_rewrite_counts(
        self,
        sql: str,
        *,
        property_name: str,
        property_type: PropertyType | None,
        materialized: bool = True,
        column_type: str | None = None,
        is_nullable: bool = True,
    ) -> dict[str, int]:
        """Run the full prepare+print pass over `sql` and return what the range-rewrite counter recorded."""
        if materialized:
            materialize(
                "events",
                property_name,
                column_name=f"mat_{property_name}",
                is_nullable=is_nullable,
                column_type=column_type,
            )
        if property_type is not None:
            PropertyDefinition.objects.get_or_create(
                team=self.team,
                project_id=self.team.project_id,
                name=property_name,
                type=PropertyDefinition.Type.EVENT,
                defaults={"property_type": property_type},
            )
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.AUTO),
        )
        # Inject the accumulator in place of the sampling draw; the pass's finally-block emit also flushes it to
        # Prometheus, so every test here exercises the full record → emit flow.
        stats = HogQLTypeObservability(dialect="clickhouse", source="probe")
        with patch("posthog.hogql.printer.utils.create_hogql_type_observability", return_value=stats):
            prepare_and_print_ast(parse_select(sql), context, "clickhouse")
        return dict(stats.materialized_range_rewrite)

    @parameterized.expand(
        [
            ("numeric", "SELECT count() FROM events WHERE properties.revenue > 10", "revenue", PropertyType.Numeric),
            (
                "datetime",
                "SELECT count() FROM events WHERE properties.signup_at > '2024-01-01'",
                "signup_at",
                PropertyType.Datetime,
            ),
        ]
    )
    def test_range_over_string_column_records_skipped(
        self, _name: str, sql: str, property_name: str, property_type: PropertyType
    ) -> None:
        # The regression guard: a numeric/datetime property range filter materializes to a string column, the bare
        # range rewrite is unsafe (lexicographic), so it is "skipped" — not silently dropped, which left the counter
        # empty.
        counts = self._range_rewrite_counts(sql, property_name=property_name, property_type=property_type)
        self.assertEqual(counts, {"skipped": 1})

    def test_range_over_typed_nullable_column_records_fired_if_null(self):
        # A typed (non-string) nullable materialized column can be compared bare with a null guard.
        counts = self._range_rewrite_counts(
            "SELECT count() FROM events WHERE properties.revenue > 10",
            property_name="revenue",
            column_type="Nullable(Float64)",
            property_type=PropertyType.Numeric,
        )
        self.assertEqual(counts, {"fired_if_null": 1})

    def test_range_over_non_nullable_string_column_records_fired_compare(self):
        # A string/untyped property over a non-nullable string materialized column rewrites bare (sentinels excluded
        # inline), so it fires without a null guard.
        counts = self._range_rewrite_counts(
            "SELECT count() FROM events WHERE properties.untyped_tag > 'abc'",
            property_name="untyped_tag",
            is_nullable=False,
            property_type=None,
        )
        self.assertEqual(counts, {"fired_compare": 1})

    def test_range_over_unmaterialized_property_records_nothing(self):
        # No backing column: not a materialized range comparison, so the counter must stay untouched.
        counts = self._range_rewrite_counts(
            "SELECT count() FROM events WHERE properties.not_materialized > 10",
            property_name="not_materialized",
            property_type=PropertyType.Numeric,
            materialized=False,
        )
        self.assertEqual(counts, {})

    def test_skipped_outcome_flows_through_to_prometheus(self):
        labels = {"engine": "current", "dialect": "clickhouse", "source": "probe", "result": "skipped"}
        before = REGISTRY.get_sample_value("hogql_materialized_range_rewrite_total", labels) or 0.0

        self._range_rewrite_counts(
            "SELECT count() FROM events WHERE properties.revenue > 10",
            property_name="revenue",
            property_type=PropertyType.Numeric,
        )

        after = REGISTRY.get_sample_value("hogql_materialized_range_rewrite_total", labels) or 0.0
        self.assertEqual(after - before, 1)

    def test_every_range_operator_records(self):
        # All four range operators in one WHERE: each comparison reaches the optimizer and records independently.
        counts = self._range_rewrite_counts(
            "SELECT count() FROM events WHERE properties.revenue < 10 AND properties.revenue <= 10"
            " AND properties.revenue > 10 AND properties.revenue >= 10",
            property_name="revenue",
            property_type=PropertyType.Numeric,
        )
        self.assertEqual(counts, {"skipped": 4})
