# isort: skip_file
# Needs to be first to set up django environment
from .helpers import benchmark_clickhouse, no_materialized_columns
from datetime import timedelta
from ee.clickhouse.materialized_columns.analyze import (
    backfill_materialized_columns,
    materialize,
)
from ee.clickhouse.materialized_columns.columns import MaterializedColumn
from posthog.queries.property_values import (
    get_person_property_values_for_key,
)
from posthog.hogql_queries.property_values_query_runner import PropertyValuesQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.utils.timestamp_utils import get_earliest_timestamp_unfiltered
from posthog.schema import PropertyType, PropertyValuesQuery
from posthog.models import Team, Organization
from products.cohorts.backend.models.cohort import Cohort
from posthog.models.property import PropertyName, TableWithProperties

MATERIALIZED_PROPERTIES: dict[TableWithProperties, list[PropertyName]] = {
    "events": [
        "$current_url",
        "$event_type",
        "$host",
    ],
    "person": [
        "$browser",
        "email",
    ],
}


class QuerySuite:
    timeout = 3000.0  # Timeout for the whole suite
    version = "v001"  # Version. Incrementing this will invalidate previous results

    team: Team
    cohort: Cohort

    @benchmark_clickhouse
    def track_earliest_timestamp(self):
        get_earliest_timestamp_unfiltered(self.team)

    @benchmark_clickhouse
    def track_event_property_values(self):
        with no_materialized_columns():
            self._run_event_property_values("$browser")

    @benchmark_clickhouse
    def track_event_property_values_materialized(self):
        self._run_event_property_values("$browser")

    def _run_event_property_values(self, key: str) -> None:
        PropertyValuesQueryRunner(
            team=self.team,
            query=PropertyValuesQuery(property_type=PropertyType.EVENT, property_key=key),
        ).run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

    @benchmark_clickhouse
    def track_person_property_values(self):
        with no_materialized_columns():
            get_person_property_values_for_key("$browser", self.team)

    @benchmark_clickhouse
    def track_person_property_values_materialized(self):
        get_person_property_values_for_key("$browser", self.team)

    def setup(self):
        for table, properties in MATERIALIZED_PROPERTIES.items():
            columns = [
                materialize(table, property)
                for property in (
                    set(properties) - {column.details.property_name for column in MaterializedColumn.get_all(table)}
                )
            ]
            backfill_materialized_columns(
                table,
                columns,
                backfill_period=timedelta(days=1_000),
            )

        # :TRICKY: Data in benchmark servers has ID=2
        team = Team.objects.filter(id=2).first()
        if team is None:
            organization = Organization.objects.create()
            team = Team.objects.create(id=2, organization=organization, name="The Bakery")
        self.team = team

        cohort = Cohort.objects.filter(name="benchmarking cohort").first()
        if cohort is None:
            cohort = Cohort.objects.create(
                team_id=2,
                name="benchmarking cohort",
                groups=[
                    {
                        "properties": [
                            {
                                "key": "email",
                                "operator": "icontains",
                                "value": ".com",
                                "type": "person",
                            }
                        ]
                    }
                ],
            )
            cohort.calculate_people_ch(pending_version=0)
        self.cohort = cohort
