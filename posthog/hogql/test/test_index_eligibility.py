from typing import cast

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import HogLanguage, HogQLMetadata

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
    eligibility_from_plan,
)
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.parser import parse_select
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
        value_type=ast.StringType(nullable=True),
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
            (PredicateIndexVerdict.INDEXED, _plan(kind=PropertySourceKind.MATERIALIZED_COLUMN, bloom=True), False),
            (PredicateIndexVerdict.UNINDEXED_JSON, _plan(restricted=True), False),
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
                    start=None,
                    end=None,
                )
                for verdict in verdicts
            )
        )

        assert report.usage == expected


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

    def test_metadata_reports_index_usage_for_a_json_backed_filter(self) -> None:
        PropertyDefinition.objects.create(team=self.team, name="duration", property_type=PropertyType.Numeric)

        response = get_hogql_metadata(
            HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query="select count() from events where properties.duration > 100",
            ),
            self.team,
        )

        assert response.isValid is True
        assert response.isUsingIndices == QueryIndexUsage.NO
        assert response.index_usage is not None
        [usage] = response.index_usage
        assert usage.property_name == "duration"
        assert usage.fix is not None

    def test_metadata_reports_no_index_usage_without_property_filters(self) -> None:
        response = get_hogql_metadata(
            HogQLMetadata(
                kind="HogQLMetadata",
                language=HogLanguage.HOG_QL,
                query="select count() from events where event = '$pageview'",
            ),
            self.team,
        )

        assert response.isUsingIndices == QueryIndexUsage.UNDECISIVE
        assert response.index_usage == []
