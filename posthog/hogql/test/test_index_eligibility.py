from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import HogLanguage, HogQLMetadata, HogQLMetadataResponse

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.index_eligibility import (
    IndexEligibilityReport,
    IndexKind,
    PredicateIndexEligibility,
    PredicateIndexVerdict,
    analyze_index_eligibility,
    build_index_eligibility_report,
    eligibility_from_plan,
)
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.parser import parse_select
from posthog.hogql.property_metadata import MaterializedColumnsByTable, PropertyMetadata
from posthog.hogql.property_planner import (
    ComparisonCompatibility,
    PropertyAccessPlan,
    PropertyComparisonPlan,
    PropertyLiteralConversion,
    PropertyMinmaxBlocker,
    PropertyScope,
    PropertySourceKind,
    PropertySourcePlan,
)
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.property_types import build_property_swapper

from posthog.schema_enums import QueryIndexUsage

from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.event_definitions.backend.property_type import PropertyType

from ee.clickhouse.materialized_columns.columns import MaterializedColumn, MaterializedColumnDetails

Op = ast.CompareOperationOp


def _plan(
    *,
    operator: ast.CompareOperationOp = Op.Eq,
    kind: PropertySourceKind = PropertySourceKind.JSON,
    minmax: bool = False,
    bloom: bool = False,
    ngram_lower: bool = False,
    bloom_lower: bool = False,
    blocker: PropertyMinmaxBlocker | None = None,
    restricted: bool = False,
    semantic_type: ast.ConstantType | None = None,
    physical_type: ast.ConstantType | None = None,
    value_type: ast.ConstantType | None = None,
) -> PropertyComparisonPlan:
    source = PropertySourcePlan(
        kind=kind,
        table_name="events",
        field_name="properties",
        column_name="properties" if kind == PropertySourceKind.JSON else "mat_duration",
        physical_type=physical_type or ast.StringType(nullable=True),
        is_nullable=True,
        has_minmax_index=minmax,
        has_bloom_filter_index=bloom,
        has_ngram_lower_index=ngram_lower,
        has_bloom_filter_lower_index=bloom_lower,
        restricted=restricted,
    )
    access = PropertyAccessPlan(
        property_name="duration",
        scope=PropertyScope.EVENT,
        semantic_type=semantic_type or ast.StringType(nullable=True),
        source=source,
        property_type=ast.PropertyType(
            chain=["duration"],
            field_type=ast.FieldType(name="properties", table_type=ast.TableType(table=EventsTable())),
        ),
    )
    return PropertyComparisonPlan(
        access=access,
        property_side="left",
        operator=operator,
        value_type=value_type or ast.StringType(nullable=True),
        semantic_compatibility=ComparisonCompatibility.DEFINITELY_COMPATIBLE,
        physical_compatibility=ComparisonCompatibility.DEFINITELY_COMPATIBLE,
        literal_conversion=PropertyLiteralConversion.NONE,
        source_matches_semantics=blocker != PropertyMinmaxBlocker.SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE,
        minmax_blocker=blocker,
    )


class TestIndexEligibilityVerdicts(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "json_equality_has_no_index",
                _plan(),
                PredicateIndexVerdict.UNINDEXED_JSON,
                (),
            ),
            (
                "bloom_filter_covers_equality",
                _plan(kind=PropertySourceKind.MATERIALIZED_COLUMN, bloom=True),
                PredicateIndexVerdict.INDEXED,
                (IndexKind.BLOOM_FILTER,),
            ),
            (
                "bloom_filter_does_not_cover_ranges",
                _plan(operator=Op.Gt, kind=PropertySourceKind.MATERIALIZED_COLUMN, bloom=True),
                PredicateIndexVerdict.UNINDEXED_COLUMN,
                (),
            ),
            (
                "minmax_covers_ranges",
                _plan(operator=Op.Gt, kind=PropertySourceKind.MATERIALIZED_COLUMN, minmax=True),
                PredicateIndexVerdict.INDEXED,
                (IndexKind.MINMAX,),
            ),
            (
                "storage_type_mismatch_defeats_the_index",
                _plan(
                    operator=Op.Gt,
                    kind=PropertySourceKind.MATERIALIZED_COLUMN,
                    minmax=True,
                    blocker=PropertyMinmaxBlocker.SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE,
                ),
                PredicateIndexVerdict.BLOCKED,
                (),
            ),
            (
                "value_type_mismatch_defeats_the_index",
                _plan(
                    operator=Op.Gt,
                    kind=PropertySourceKind.MATERIALIZED_COLUMN,
                    minmax=True,
                    blocker=PropertyMinmaxBlocker.VALUE_TYPE_NOT_SOURCE_COMPATIBLE,
                ),
                PredicateIndexVerdict.BLOCKED,
                (),
            ),
            (
                "negated_equality_prunes_nothing",
                _plan(operator=Op.NotEq, kind=PropertySourceKind.MATERIALIZED_COLUMN, minmax=True, bloom=True),
                PredicateIndexVerdict.OPERATOR_NOT_INDEXABLE,
                (),
            ),
            (
                "regex_prunes_nothing",
                _plan(operator=Op.Regex, kind=PropertySourceKind.MATERIALIZED_COLUMN, minmax=True, bloom=True),
                PredicateIndexVerdict.OPERATOR_NOT_INDEXABLE,
                (),
            ),
            (
                "ngram_covers_case_insensitive_like",
                _plan(operator=Op.ILike, kind=PropertySourceKind.MATERIALIZED_COLUMN, ngram_lower=True),
                PredicateIndexVerdict.INDEXED,
                (IndexKind.NGRAM_LOWER,),
            ),
            (
                "case_sensitive_like_is_not_claimed_as_indexed",
                _plan(operator=Op.Like, kind=PropertySourceKind.MATERIALIZED_COLUMN, ngram_lower=True),
                PredicateIndexVerdict.OPERATOR_NOT_INDEXABLE,
                (),
            ),
            (
                "property_group_equality_uses_its_bloom_filter",
                _plan(kind=PropertySourceKind.PROPERTY_GROUP, bloom=True),
                PredicateIndexVerdict.INDEXED,
                (IndexKind.BLOOM_FILTER,),
            ),
            (
                "absent_index_is_not_a_type_blocker",
                _plan(blocker=PropertyMinmaxBlocker.NO_MINMAX_INDEX),
                PredicateIndexVerdict.UNINDEXED_JSON,
                (),
            ),
            (
                "in_against_matching_members_still_prunes",
                _plan(
                    operator=Op.In,
                    kind=PropertySourceKind.MATERIALIZED_COLUMN,
                    minmax=True,
                    blocker=PropertyMinmaxBlocker.VALUE_TYPE_NOT_SOURCE_COMPATIBLE,
                    value_type=ast.TupleType(item_types=[ast.StringType(), ast.StringType()]),
                ),
                PredicateIndexVerdict.INDEXED,
                (IndexKind.MINMAX,),
            ),
            (
                "in_against_mismatched_members_does_not",
                _plan(
                    operator=Op.In,
                    kind=PropertySourceKind.MATERIALIZED_COLUMN,
                    minmax=True,
                    blocker=PropertyMinmaxBlocker.VALUE_TYPE_NOT_SOURCE_COMPATIBLE,
                    value_type=ast.TupleType(item_types=[ast.IntegerType(), ast.IntegerType()]),
                ),
                PredicateIndexVerdict.BLOCKED,
                (),
            ),
        ]
    )
    def test_verdict_for_operator_and_source(
        self,
        _name: str,
        plan: PropertyComparisonPlan,
        expected_verdict: PredicateIndexVerdict,
        expected_indexes: tuple[IndexKind, ...],
    ) -> None:
        eligibility = eligibility_from_plan(plan)

        assert eligibility.verdict == expected_verdict
        assert eligibility.usable_indexes == expected_indexes

    @parameterized.expand(
        [
            (PredicateIndexVerdict.UNINDEXED_JSON, _plan(), True),
            (
                PredicateIndexVerdict.BLOCKED,
                _plan(minmax=True, blocker=PropertyMinmaxBlocker.VALUE_TYPE_NOT_SOURCE_COMPATIBLE),
                True,
            ),
            (
                PredicateIndexVerdict.BLOCKED,
                _plan(
                    operator=Op.Gt,
                    kind=PropertySourceKind.MATERIALIZED_COLUMN,
                    minmax=True,
                    blocker=PropertyMinmaxBlocker.SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE,
                    semantic_type=ast.FloatType(nullable=True),
                ),
                True,
            ),
            (PredicateIndexVerdict.INDEXED, _plan(kind=PropertySourceKind.MATERIALIZED_COLUMN, bloom=True), False),
        ]
    )
    def test_only_actionable_verdicts_carry_a_fix(
        self,
        expected_verdict: PredicateIndexVerdict,
        plan: PropertyComparisonPlan,
        expects_fix: bool,
    ) -> None:
        eligibility = eligibility_from_plan(plan)

        assert eligibility.verdict == expected_verdict
        assert (eligibility.fix is not None) == expects_fix

    @parameterized.expand(
        [
            (
                "value_type_mismatch_is_fixable_in_the_query",
                _plan(minmax=True, blocker=PropertyMinmaxBlocker.VALUE_TYPE_NOT_SOURCE_COMPATIBLE),
                True,
            ),
            (
                "source_type_mismatch_is_not",
                _plan(
                    operator=Op.Gt,
                    kind=PropertySourceKind.MATERIALIZED_COLUMN,
                    minmax=True,
                    blocker=PropertyMinmaxBlocker.SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE,
                    semantic_type=ast.FloatType(nullable=True),
                ),
                False,
            ),
            ("json_reads_are_not", _plan(), False),
            ("indexed_reads_are_not", _plan(kind=PropertySourceKind.MATERIALIZED_COLUMN, bloom=True), False),
        ]
    )
    def test_only_query_fixable_predicates_get_a_marker(
        self, _name: str, plan: PropertyComparisonPlan, expects_marker: bool
    ) -> None:
        assert eligibility_from_plan(plan).editor_actionable == expects_marker

    @parameterized.expand(
        [
            (
                "value_type_mismatch",
                _plan(minmax=True, blocker=PropertyMinmaxBlocker.VALUE_TYPE_NOT_SOURCE_COMPATIBLE),
            ),
            (
                "in_against_mismatched_members",
                _plan(
                    operator=Op.In,
                    kind=PropertySourceKind.MATERIALIZED_COLUMN,
                    minmax=True,
                    blocker=PropertyMinmaxBlocker.VALUE_TYPE_NOT_SOURCE_COMPATIBLE,
                    value_type=ast.TupleType(item_types=[ast.IntegerType(), ast.IntegerType()]),
                ),
            ),
        ]
    )
    def test_marked_predicates_carry_an_ai_prompt_never_prose(self, _name: str, plan: PropertyComparisonPlan) -> None:
        # `HogQLNotice.fix` is substituted into the query verbatim by the editor's quick fix, so the
        # marker path may only ever emit an `ai_prompt:` instruction. `metadata.py` derives that value
        # from `ai_fix_prompt`, so a marked predicate without one would put nothing there and a marked
        # predicate carrying only prose would put advice into the user's query.
        eligibility = eligibility_from_plan(plan)

        assert eligibility.editor_actionable is True
        assert eligibility.ai_fix_prompt is not None

    def test_a_denied_property_reports_the_same_as_an_unmaterialized_one(self) -> None:
        denied = eligibility_from_plan(_plan(restricted=True))
        allowed = eligibility_from_plan(_plan())

        assert denied == allowed

    def test_negation_overrides_an_otherwise_usable_index(self) -> None:
        plan = _plan(kind=PropertySourceKind.MATERIALIZED_COLUMN, bloom=True)

        assert eligibility_from_plan(plan).verdict == PredicateIndexVerdict.INDEXED
        assert eligibility_from_plan(plan, negated=True).verdict == PredicateIndexVerdict.OPERATOR_NOT_INDEXABLE

    @parameterized.expand(
        [
            ([], QueryIndexUsage.UNDECISIVE),
            ([PredicateIndexVerdict.INDEXED], QueryIndexUsage.YES),
            ([PredicateIndexVerdict.INDEXED, PredicateIndexVerdict.UNINDEXED_JSON], QueryIndexUsage.PARTIAL),
            ([PredicateIndexVerdict.UNINDEXED_JSON, PredicateIndexVerdict.BLOCKED], QueryIndexUsage.NO),
        ]
    )
    def test_report_usage_summarizes_predicates(
        self, verdicts: list[PredicateIndexVerdict], expected: QueryIndexUsage
    ) -> None:
        report = IndexEligibilityReport(
            predicates=tuple(
                PredicateIndexEligibility(
                    property_name="duration",
                    scope=PropertyScope.EVENT,
                    operator=Op.Eq,
                    source_kind=PropertySourceKind.JSON,
                    source_label="JSON blob",
                    column_name="properties",
                    semantic_type="String",
                    physical_type="String",
                    available_indexes=(),
                    usable_indexes=(),
                    verdict=verdict,
                    blocker=None,
                    message="",
                    fix=None,
                    ai_fix_prompt=None,
                    start=None,
                    end=None,
                )
                for verdict in verdicts
            )
        )

        assert report.usage == expected


def _materialized(property_name: str, *, minmax: bool = False, bloom: bool = False) -> MaterializedColumn:
    return MaterializedColumn(
        name=f"mat_{property_name}",
        details=MaterializedColumnDetails(
            table_column="properties",
            property_name=property_name,
            is_disabled=False,
        ),
        is_nullable=False,
        has_minmax_index=minmax,
        has_bloom_filter_index=bloom,
    )


class TestIndexEligibilityThroughThePlanner(BaseTest):
    """Verdicts reached through the real planner rather than a constructed plan.

    Every other verdict test hands `eligibility_from_plan` a `PropertyComparisonPlan` built by the
    test, so it proves the operator mapping and nothing about whether `plan_property_comparison`
    emits such a plan for a real query. These two cover that seam: a synthetic materialized-column
    registry stands in for ClickHouse, and the query goes through resolution and planning as it does
    in production.
    """

    def _report(
        self,
        query: str,
        *,
        columns: MaterializedColumnsByTable,
        property_types: dict[str, dict[str, str | None]] | None = None,
    ) -> IndexEligibilityReport:
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(context.team_id, modifiers=context.modifiers, team=context.team)
        # Pre-setting the bundle stands in for ClickHouse and skips the Postgres-backed loader, so the
        # planner sees a materialized column with the indexes this test is about.
        context.property_metadata = PropertyMetadata(
            event_properties=property_types or {},
            materialized_columns=lambda: columns,
        )
        return build_index_eligibility_report(parse_select(query), context)

    def test_materialized_column_with_a_bloom_filter_is_indexed(self) -> None:
        report = self._report(
            "select count() from events where properties.$browser = 'Chrome'",
            columns={"events": {("$browser", "properties"): _materialized("$browser", bloom=True)}},
        )

        [predicate] = report.predicates
        assert predicate.verdict == PredicateIndexVerdict.INDEXED
        assert predicate.usable_indexes == (IndexKind.BLOOM_FILTER,)
        assert report.usage == QueryIndexUsage.YES

    def test_numeric_property_stored_as_string_is_blocked(self) -> None:
        report = self._report(
            "select count() from events where properties.duration > 100",
            columns={"events": {("duration", "properties"): _materialized("duration", minmax=True)}},
            property_types={"duration": {"type": PropertyType.Numeric.value}},
        )

        [predicate] = report.predicates
        assert predicate.verdict == PredicateIndexVerdict.BLOCKED
        assert predicate.usable_indexes == ()
        # The advice is real but not a query edit, so it must not become an editor marker.
        assert predicate.fix is not None
        assert predicate.editor_actionable is False


class TestIndexEligibilityAnalysis(BaseTest):
    def _report(self, query: str) -> IndexEligibilityReport:
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(context.team_id, modifiers=context.modifiers, team=context.team)
        node = cast(ast.SelectQuery, resolve_types(parse_select(query), context, dialect="clickhouse"))
        build_property_swapper(node, context)
        return analyze_index_eligibility(node, context)

    def test_only_filtering_positions_are_reported(self) -> None:
        report = self._report(
            "select properties.selected = '1' from events "
            "where properties.filtered = '2' "
            "group by properties.grouped having properties.grouped != '3'"
        )

        assert [predicate.property_name for predicate in report.predicates] == ["filtered"]

    def test_predicates_inside_a_boolean_tree_are_reported(self) -> None:
        report = self._report(
            "select count() from events where (properties.a = '1' or properties.b = '2') and not (properties.c = '3')"
        )

        verdicts = {predicate.property_name: predicate.verdict for predicate in report.predicates}
        assert verdicts == {
            "a": PredicateIndexVerdict.UNINDEXED_JSON,
            "b": PredicateIndexVerdict.UNINDEXED_JSON,
            "c": PredicateIndexVerdict.OPERATOR_NOT_INDEXABLE,
        }

    def _metadata(self, query: str) -> HogQLMetadataResponse:
        with patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=True):
            return get_hogql_metadata(
                HogQLMetadata(
                    kind="HogQLMetadata",
                    language=HogLanguage.HOG_QL,
                    query=query,
                    indexUsage=True,
                ),
                self.team,
            )

    def test_metadata_reports_index_usage_for_a_json_backed_filter(self) -> None:
        PropertyDefinition.objects.create(team=self.team, name="duration", property_type=PropertyType.Numeric)

        response = self._metadata("select count() from events where properties.duration > 100")

        assert response.isValid is True
        assert response.isUsingIndices == QueryIndexUsage.NO
        assert response.index_usage is not None
        [usage] = response.index_usage
        assert usage.property_name == "duration"
        assert usage.fix is not None

    def test_metadata_reports_no_index_usage_without_property_filters(self) -> None:
        response = self._metadata("select count() from events where event = '$pageview'")

        assert response.isUsingIndices == QueryIndexUsage.UNDECISIVE
        assert response.index_usage == []
