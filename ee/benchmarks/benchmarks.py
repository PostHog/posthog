# isort: skip_file
# Needs to be first to set up django environment
from .helpers import benchmark_clickhouse, no_materialized_columns
from datetime import timedelta
from ee.clickhouse.materialized_columns.analyze import (
    backfill_materialized_columns,
    materialize,
)
from ee.clickhouse.materialized_columns.columns import MaterializedColumn
from ee.clickhouse.queries.stickiness import ClickhouseStickiness
from ee.clickhouse.queries.funnels.funnel_correlation import FunnelCorrelation
from posthog.queries.funnels import ClickhouseFunnel
from posthog.queries.property_values import (
    get_property_values_for_key,
    get_person_property_values_for_key,
)
from posthog.queries.session_recordings.session_recording_list import (
    SessionRecordingList,
)
from posthog.queries.util import get_earliest_timestamp
from posthog.models import Action, Cohort, Team, Organization
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.filter import Filter
from posthog.models.property import PropertyName, TableWithProperties
from posthog.constants import FunnelCorrelationType

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

DATE_RANGE = {"date_from": "2021-01-01", "date_to": "2021-10-01", "interval": "week"}
SHORT_DATE_RANGE = {
    "date_from": "2021-07-01",
    "date_to": "2021-10-01",
    "interval": "week",
}
SESSIONS_DATE_RANGE = {"date_from": "2021-11-17", "date_to": "2021-11-22"}


class QuerySuite:
    timeout = 3000.0  # Timeout for the whole suite
    version = "v001"  # Version. Incrementing this will invalidate previous results

    team: Team
    cohort: Cohort

    @benchmark_clickhouse
    def track_funnel_normal(self):
        filter = Filter(
            data={
                "insight": "FUNNELS",
                "events": [
                    {"id": "user signed up", "order": 0},
                    {"id": "insight analyzed", "order": 1},
                ],
                **DATE_RANGE,
            },
            team=self.team,
        )
        ClickhouseFunnel(filter, self.team).run()

    @benchmark_clickhouse
    def track_correlations_by_events(self):
        filter = Filter(
            data={
                "events": [{"id": "user signed up"}, {"id": "insight analyzed"}],
                **SHORT_DATE_RANGE,
            },
            team=self.team,
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

    @benchmark_clickhouse
    def track_stickiness(self):
        filter = StickinessFilter(
            data={
                "insight": "STICKINESS",
                "events": [{"id": "$pageview"}],
                "shown_as": "Stickiness",
                "display": "ActionsLineGraph",
                **DATE_RANGE,
            },
            team=self.team,
        )

        ClickhouseStickiness().run(filter, self.team)

    @benchmark_clickhouse
    def track_stickiness_filter_by_person_property(self):
        filter = StickinessFilter(
            data={
                "insight": "STICKINESS",
                "events": [{"id": "$pageview"}],
                "shown_as": "Stickiness",
                "display": "ActionsLineGraph",
                "properties": [
                    {
                        "key": "email",
                        "operator": "icontains",
                        "value": ".com",
                        "type": "person",
                    }
                ],
                **DATE_RANGE,
            },
            team=self.team,
        )

        with no_materialized_columns():
            ClickhouseStickiness().run(filter, self.team)

    @benchmark_clickhouse
    def track_stickiness_filter_by_person_property_materialized(self):
        filter = StickinessFilter(
            data={
                "insight": "STICKINESS",
                "events": [{"id": "$pageview"}],
                "shown_as": "Stickiness",
                "display": "ActionsLineGraph",
                "properties": [
                    {
                        "key": "email",
                        "operator": "icontains",
                        "value": ".com",
                        "type": "person",
                    }
                ],
                **DATE_RANGE,
            },
            team=self.team,
        )

        ClickhouseStickiness().run(filter, self.team)

    @benchmark_clickhouse
    def track_session_recordings_list(self):
        filter = SessionRecordingsFilter(data=SESSIONS_DATE_RANGE, team=self.team)

        SessionRecordingList(filter, self.team).run()

    @benchmark_clickhouse
    def track_session_recordings_list_event_filter(self):
        filter = SessionRecordingsFilter(
            data={"events": [{"id": "$pageview"}], **SESSIONS_DATE_RANGE},
            team=self.team,
        )

        SessionRecordingList(filter, self.team).run()

    @benchmark_clickhouse
    def track_earliest_timestamp(self):
        get_earliest_timestamp(2)

    @benchmark_clickhouse
    def track_event_property_values(self):
        with no_materialized_columns():
            get_property_values_for_key("$browser", self.team)

    @benchmark_clickhouse
    def track_event_property_values_materialized(self):
        get_property_values_for_key("$browser", self.team)

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
