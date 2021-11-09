# isort: skip_file
# Needs to be first to set up django environment
from .helpers import *

from datetime import timedelta
from typing import List, Tuple

from ee.clickhouse.materialized_columns import backfill_materialized_columns, get_materialized_columns, materialize
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.queries.funnels.funnel_correlation import FunnelCorrelation
from posthog.models import Action, ActionStep, Cohort, Team, Organization
from posthog.models.filters.filter import Filter
from posthog.models.property import PropertyName, TableWithProperties
from posthog.constants import FunnelCorrelationType

MATERIALIZED_PROPERTIES: List[Tuple[TableWithProperties, PropertyName]] = [
    ("events", "$host"),
    ("events", "$current_url"),
    ("events", "$event_type"),
    ("person", "email"),
    ("person", "$browser"),
]

DATE_RANGE = {"date_from": "2021-01-01", "date_to": "2021-10-01", "interval": "week"}
SHORT_DATE_RANGE = {"date_from": "2021-07-01", "date_to": "2021-10-01", "interval": "week"}


class QuerySuite:
    timeout = 3000.0  # Timeout for the whole suite
    version = "v001"  # Version. Incrementing this will invalidate previous results

    team: Team
    cohort: Cohort

    @benchmark_clickhouse
    def track_trends_no_filter(self):
        filter = Filter(data={"events": [{"id": "$pageview"}], **DATE_RANGE})
        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_event_property_filter(self):
        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "properties": [
                    {
                        "key": "$host",
                        "operator": "is_not",
                        "value": [
                            "localhost:8000",
                            "localhost:5000",
                            "127.0.0.1:8000",
                            "127.0.0.1:3000",
                            "localhost:3000",
                        ],
                    }
                ],
                **SHORT_DATE_RANGE,
            }
        )

        with no_materialized_columns():
            ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_event_property_filter_materialized(self):
        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "properties": [
                    {
                        "key": "$host",
                        "operator": "is_not",
                        "value": [
                            "localhost:8000",
                            "localhost:5000",
                            "127.0.0.1:8000",
                            "127.0.0.1:3000",
                            "localhost:3000",
                        ],
                    }
                ],
                **DATE_RANGE,
            }
        )
        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_person_property_filter(self):
        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
                **DATE_RANGE,
            }
        )

        with no_materialized_columns():
            ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_person_property_filter_materialized(self):
        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
                **DATE_RANGE,
            }
        )

        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_filter_by_cohort_precalculated(self):
        self.cohort.last_calculation = now()
        self.cohort.save()

        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "id", "value": self.cohort.pk, "type": "cohort"}],
                **DATE_RANGE,
            },
            team=self.team,
        )
        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_filter_by_cohort(self):
        self.cohort.last_calculation = None
        self.cohort.save()

        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "id", "value": self.cohort.pk, "type": "cohort"}],
                **DATE_RANGE,
            },
            team=self.team,
        )

        with no_materialized_columns():
            ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_filter_by_cohort_materialized(self):
        self.cohort.last_calculation = None
        self.cohort.save()

        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "properties": [{"key": "id", "value": self.cohort.pk, "type": "cohort"}],
                **DATE_RANGE,
            },
            team=self.team,
        )

        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_filter_by_action_current_url_materialized(self):
        action = Action.objects.create(team=self.team, name="docs view")
        ActionStep.objects.create(
            action=action, event="$pageview", url="docs", url_matching="contains",
        )

        filter = Filter(data={"actions": [{"id": action.id}], **DATE_RANGE}, team=self.team)
        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_filter_by_action_current_url(self):
        action = Action.objects.create(team=self.team, name="docs view")
        ActionStep.objects.create(
            action=action, event="$pageview", url="docs", url_matching="contains",
        )

        filter = Filter(data={"actions": [{"id": action.id}], **DATE_RANGE}, team=self.team)
        with no_materialized_columns():
            ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_filter_by_action_with_person_filters_materialized(self):
        action = Action.objects.create(team=self.team, name=".com-users page views")
        ActionStep.objects.create(
            action=action,
            event="$pageview",
            properties=[{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
        )

        filter = Filter(data={"actions": [{"id": action.id}], **DATE_RANGE}, team=self.team)
        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_filter_by_action_with_person_filters(self):
        action = Action.objects.create(team=self.team, name=".com-users page views")
        ActionStep.objects.create(
            action=action,
            event="$pageview",
            properties=[{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
        )

        filter = Filter(data={"actions": [{"id": action.id}], **DATE_RANGE}, team=self.team)
        with no_materialized_columns():
            ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_correlations_by_events(self):
        filter = Filter(
            data={"events": [{"id": "user signed up"}, {"id": "insight analyzed"}], **SHORT_DATE_RANGE,}, team=self.team
        )

        FunnelCorrelation(filter, self.team).run()

    @benchmark_clickhouse
    def track_correlations_by_properties_materialized(self):
        filter = Filter(
            data={
                "events": [{"id": "user signed up"}, {"id": "insight analyzed"}],
                **SHORT_DATE_RANGE,
                "funnel_correlation_type": FunnelCorrelationType.PROPERTIES,
                "funnel_correlation_names": ["$browser"],
            },
            team=self.team,
        )
        FunnelCorrelation(filter, self.team).run()

    @benchmark_clickhouse
    def track_correlations_by_properties(self):
        filter = Filter(
            data={
                "events": [{"id": "user signed up"}, {"id": "insight analyzed"}],
                **SHORT_DATE_RANGE,
                "funnel_correlation_type": FunnelCorrelationType.PROPERTIES,
                "funnel_correlation_names": ["$browser"],
            },
            team=self.team,
        )
        with no_materialized_columns():
            FunnelCorrelation(filter, self.team).run()

    @benchmark_clickhouse
    def track_correlations_by_event_properties(self):
        filter = Filter(
            data={
                "events": [{"id": "user signed up"}, {"id": "insight analyzed"}],
                **SHORT_DATE_RANGE,
                "funnel_correlation_type": FunnelCorrelationType.EVENT_WITH_PROPERTIES,
                "funnel_correlation_event_names": ["$autocapture"],
            },
            team=self.team,
        )
        with no_materialized_columns():
            FunnelCorrelation(filter, self.team).run()

    @benchmark_clickhouse
    def track_correlations_by_event_properties_materialized(self):
        filter = Filter(
            data={
                "events": [{"id": "user signed up"}, {"id": "insight analyzed"}],
                **SHORT_DATE_RANGE,
                "funnel_correlation_type": FunnelCorrelationType.EVENT_WITH_PROPERTIES,
                "funnel_correlation_event_names": ["$autocapture"],
            },
            team=self.team,
        )
        FunnelCorrelation(filter, self.team).run()

    def setup(self):
        for table, property in MATERIALIZED_PROPERTIES:
            if property not in get_materialized_columns(table):
                materialize(table, property)
                backfill_materialized_columns(table, [property], backfill_period=timedelta(days=1_000))

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
                groups=[{"properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}]}],
            )
            cohort.calculate_people_ch()
        self.cohort = cohort
