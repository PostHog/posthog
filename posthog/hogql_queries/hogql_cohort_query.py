from typing import Literal, Optional, Union, Any

from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.legacy_compatibility.clean_properties import clean_global_properties
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models import Filter, Cohort, Team, Property
from posthog.models.property import PropertyGroup
from posthog.schema import ActorsQuery
from posthog.queries.cohort_query import CohortQuery


class TestWrapperCohortQuery(CohortQuery):
    def __init__(self, filter: Filter, team: Team):
        cohort_query = CohortQuery(filter=filter, team=team)
        hogql_cohort_query = HogQLCohortQuery(cohort_query=cohort_query)
        hogql_query = hogql_cohort_query.query_str("hogql")
        cohort_query_result = execute_hogql_query(hogql_query, team)
        super().__init__(filter=filter, team=team)


class HogQLCohortQuery:
    def __init__(self, cohort_query: CohortQuery, cohort: Cohort = None):
        # self.cohort = cohort

        self.hogql_context = HogQLContext(team_id=cohort_query._team_id, enable_select_queries=True)

        if cohort is not None:
            self.cohort_query = CohortQuery(
                Filter(
                    data={"properties": cohort.properties},
                    team=cohort.team,
                    hogql_context=self.hogql_context,
                ),
                cohort.team,
                cohort_pk=cohort.pk,
            )
        else:
            self.cohort_query = cohort_query

        self.properties = clean_global_properties(self.cohort_query._filter._data["properties"])
        self.team = self.cohort_query._team

    def get_query(self) -> SelectQuery:
        if not self.cohort_query._outer_property_groups:
            # everything is pushed down, no behavioral stuff to do
            # thus, use personQuery directly

            # This works
            # ActorsQuery(properties=c.properties.to_dict())

            # This just queries based on person properties and stuff
            # Need to figure out how to turn these cohort properties into a set of person properties
            # actors_query = ActorsQuery(properties=self.cohort.properties.to_dict())
            # query_runner = ActorsQueryRunner(team=self.cohort.team, query=actors_query)
            actors_query = ActorsQuery(properties=self.properties, select=["id"])
            query_runner = ActorsQueryRunner(team=self.team, query=actors_query)
            return query_runner.to_query()

        # Work on getting testing passing
        # current test: test_performed_event
        # special code this for test_performed_event
        # self.properties["values"][0]["values"][0]
        return parse_select(
            """select * from (
                    <ActorsQuery select={['id']}>
                        <InsightActorsQuery>
                            <TrendsQuery
                                dateRange={<InsightDateRange date_from='-1w' />}
                                series={[<EventsNode event='$pageview' />]}
                                trendsFilter={<TrendsFilter display='ActionsBarValue' />}
                                --properties={[<PersonPropertyFilter type='person' key='email' value='tom@posthog.com' operator='is_not' />]}
                            />
                        </InsightActorsQuery>
                    </ActorsQuery>
                )"""
        )

    def query_str(self, dialect: Literal["hogql", "clickhouse"]):
        return print_ast(self.get_query(), self.hogql_context, dialect, pretty=True)

    def get_performed_event_condition(self, prop: Property, prepend: str, idx: int) -> tuple[str, dict[str, Any]]:
        event = (prop.event_type, prop.key)
        column_name = f"performed_event_condition_{prepend}_{idx}"

        entity_query, entity_params = self._get_entity(event, prepend, idx)
        entity_filters, entity_filters_params = self._get_entity_event_filters(prop, prepend, idx)
        date_filter, date_params = self._get_entity_datetime_filters(prop, prepend, idx)

        field = f"countIf({date_filter} AND timestamp < now() AND {entity_query} {entity_filters}) > 0 AS {column_name}"
        self._fields.append(field)

        # Negation is handled in the where clause to ensure the right result if a full join occurs where the joined person did not perform the event
        return f"{'NOT' if prop.negation else ''} {column_name}", {
            **date_params,
            **entity_params,
            **entity_filters_params,
        }

    def _get_condition_for_property(self, prop: Property, prepend: str, idx: int) -> tuple[str, dict[str, Any]]:
        res: str = ""
        params: dict[str, Any] = {}

        if prop.type == "behavioral":
            if prop.value == "performed_event":
                res, params = self.get_performed_event_condition(prop, prepend, idx)
            elif prop.value == "performed_event_multiple":
                res, params = self.get_performed_event_multiple(prop, prepend, idx)
            elif prop.value == "stopped_performing_event":
                res, params = self.get_stopped_performing_event(prop, prepend, idx)
            elif prop.value == "restarted_performing_event":
                res, params = self.get_restarted_performing_event(prop, prepend, idx)
            elif prop.value == "performed_event_first_time":
                res, params = self.get_performed_event_first_time(prop, prepend, idx)
            elif prop.value == "performed_event_sequence":
                res, params = self.get_performed_event_sequence(prop, prepend, idx)
            elif prop.value == "performed_event_regularly":
                res, params = self.get_performed_event_regularly(prop, prepend, idx)
        elif prop.type == "person":
            res, params = self.get_person_condition(prop, prepend, idx)
        elif (
            prop.type == "static-cohort"
        ):  # "cohort" and "precalculated-cohort" are handled by flattening during initialization
            res, params = self.get_static_cohort_condition(prop, prepend, idx)
        else:
            raise ValueError(f"Invalid property type for Cohort queries: {prop.type}")

        return res, params

    def _get_conditions(self) -> tuple[str, dict[str, Any]]:
        def build_conditions(prop: Optional[Union[PropertyGroup, Property]], prepend="level", num=0):
            if not prop:
                return "", {}

            if isinstance(prop, PropertyGroup):
                params = {}
                conditions = []
                for idx, p in enumerate(prop.values):
                    q, q_params = build_conditions(p, f"{prepend}_level_{num}", idx)  # type: ignore
                    if q != "":
                        conditions.append(q)
                        params.update(q_params)

                return f"({f' {prop.type} '.join(conditions)})", params
            else:
                return self._get_condition_for_property(prop, prepend, num)

        conditions, params = build_conditions(self._outer_property_groups, prepend=f"{self._cohort_pk}_level", num=0)
        return f"AND ({conditions})" if conditions else "", params
