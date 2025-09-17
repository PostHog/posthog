from collections import (
    Counter,
    Counter as TCounter,
)
from collections.abc import Generator
from typing import Union, cast

from posthog.clickhouse.materialized_columns import ColumnName, get_materialized_column_for_property
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, FunnelCorrelationType
from posthog.models.action.util import get_action_tables_and_properties
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.property import PropertyIdentifier, PropertyType, TableWithProperties
from posthog.models.property.util import box_value, extract_tables_and_properties
from posthog.queries.property_optimizer import PropertyOptimizer


class FOSSColumnOptimizer:
    """
    This class is responsible for figuring out what columns can and should be materialized based on the query filter.

    This speeds up queries since clickhouse ends up selecting less data.
    """

    def __init__(
        self,
        filter: Union[
            Filter,
            PathFilter,
            RetentionFilter,
            StickinessFilter,
            PropertiesTimelineFilter,
        ],
        team_id: int,
    ):
        self.filter = filter
        self.team_id = team_id
        self.property_optimizer = PropertyOptimizer()

    @cached_property
    def event_columns_to_query(self) -> set[ColumnName]:
        "Returns a list of event table columns containing materialized properties that this query needs"

        return self.columns_to_query("events", set(self.used_properties_with_type("event")))

    @cached_property
    def person_on_event_columns_to_query(self) -> set[ColumnName]:
        "Returns a list of event table person columns containing materialized properties that this query needs"

        return self.columns_to_query("events", set(self.used_properties_with_type("person")), "person_properties")

    @cached_property
    def person_columns_to_query(self) -> set[ColumnName]:
        "Returns a list of person table columns containing materialized properties that this query needs"

        return self.columns_to_query("person", set(self.used_properties_with_type("person")))

    def columns_to_query(
        self,
        table: TableWithProperties,
        used_properties: set[PropertyIdentifier],
        table_column: str = "properties",
    ) -> set[ColumnName]:
        "Transforms a list of property names to what columns are needed for that query"
        column_names = set()
        for property_name, _, _ in used_properties:
            column = get_materialized_column_for_property(table, table_column, property_name)
            if column is not None and not column.is_nullable:
                column_names.add(column.name)
            else:
                column_names.add(table_column)
        return column_names

    @cached_property
    def is_using_person_properties(self) -> bool:
        return len(self.used_properties_with_type("person")) > 0

    @cached_property
    def is_using_cohort_propertes(self) -> bool:
        return (
            len(self.used_properties_with_type("cohort")) > 0
            or len(self.used_properties_with_type("precalculated-cohort")) > 0
            or len(self.used_properties_with_type("static-cohort")) > 0
        )

    @cached_property
    def group_types_to_query(self) -> set[GroupTypeIndex]:
        return set()

    @cached_property
    def properties_used_in_filter(self) -> TCounter[PropertyIdentifier]:
        "Returns collection of properties + types that this query would use"
        counter: TCounter[PropertyIdentifier] = extract_tables_and_properties(self.filter.property_groups.flat)

        if not isinstance(self.filter, StickinessFilter):
            # Some breakdown types read properties
            #
            # See ee/clickhouse/queries/trends/breakdown.py#get_query or
            # ee/clickhouse/queries/breakdown_props.py#get_breakdown_prop_values
            if self.filter.breakdown_type in ["event", "person"]:
                boxed_breakdown = box_value(self.filter.breakdown)
                for b in boxed_breakdown:
                    if isinstance(b, str):
                        counter[
                            (
                                b,
                                self.filter.breakdown_type,
                                self.filter.breakdown_group_type_index,
                            )
                        ] += 1

            # If we have a breakdowns attribute then make sure we pull in everything we
            # need to calculate it
            for breakdown in self.filter.breakdowns or []:
                counter[
                    (
                        breakdown["property"],
                        breakdown["type"],
                        self.filter.breakdown_group_type_index,
                    )
                ] += 1

        # Both entities and funnel exclusions can contain nested property filters
        for entity in self.entities_used_in_filter():
            counter += extract_tables_and_properties(entity.property_groups.flat)

            # Math properties are also implicitly used.
            #
            # See posthog/queries/trends/util.py#process_math
            if entity.math_property:
                counter[(entity.math_property, "event", None)] += 1

            # :TRICKY: If action contains property filters, these need to be included
            #
            # See ee/clickhouse/models/action.py#format_action_filter for an example
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                counter += get_action_tables_and_properties(entity.get_action())

        if (
            not isinstance(self.filter, StickinessFilter | PropertiesTimelineFilter)
            and self.filter.correlation_type == FunnelCorrelationType.PROPERTIES
            and self.filter.correlation_property_names
        ):
            for prop_value in self.filter.correlation_property_names:
                counter[(prop_value, "person", None)] += 1

        return counter

    def used_properties_with_type(self, property_type: PropertyType) -> TCounter[PropertyIdentifier]:
        return Counter(
            {
                (name, type, group_type_index): count
                for (
                    name,
                    type,
                    group_type_index,
                ), count in self.properties_used_in_filter.items()
                if type == property_type
            }
        )

    def entities_used_in_filter(self) -> Generator[Entity, None, None]:
        yield from self.filter.entities
        yield from cast(list[Entity], self.filter.exclusions)

        if isinstance(self.filter, RetentionFilter):
            yield self.filter.target_entity
            yield self.filter.returning_entity
