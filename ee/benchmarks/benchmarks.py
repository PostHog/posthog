# isort: skip_file
# Needs to be first to set up django environment
from .helpers import *
from datetime import timedelta
from typing import List, Tuple
from ee.clickhouse.materialized_columns import backfill_materialized_columns, get_materialized_columns, materialize
from ee.clickhouse.queries.stickiness.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.funnels.funnel_correlation import FunnelCorrelation
from ee.clickhouse.queries.funnels import ClickhouseFunnel
from ee.clickhouse.queries.property_values import get_property_values_for_key, get_person_property_values_for_key
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.queries.session_recordings.clickhouse_session_recording_list import ClickhouseSessionRecordingList
from ee.clickhouse.queries.retention.clickhouse_retention import ClickhouseRetention
from posthog.queries.util import get_earliest_timestamp
from posthog.models import Action, ActionStep, Cohort, Team, Organization
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
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
SESSIONS_DATE_RANGE = {"date_from": "2021-11-17", "date_to": "2021-11-22"}


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
    def track_trends_event_property_breakdown(self):
        filter = Filter(data={"events": [{"id": "$pageview"}], "breakdown": "$host", **DATE_RANGE,})

        with no_materialized_columns():
            ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_event_property_breakdown_materialized(self):
        filter = Filter(data={"events": [{"id": "$pageview"}], "breakdown": "$host", **DATE_RANGE,})

        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_person_property_breakdown(self):
        filter = Filter(
            data={"events": [{"id": "$pageview"}], "breakdown": "$browser", "breakdown_type": "person", **DATE_RANGE,}
        )

        with no_materialized_columns():
            ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_person_property_breakdown_materialized(self):
        filter = Filter(
            data={"events": [{"id": "$pageview"}], "breakdown": "$browser", "breakdown_type": "person", **DATE_RANGE,}
        )

        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_dau(self):
        filter = Filter(data={"events": [{"id": "$pageview", "math": "dau"}], **DATE_RANGE,})
        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_dau_person_property_filter(self):
        filter = Filter(
            data={
                "events": [{"id": "$pageview", "math": "dau"}],
                "properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
                **DATE_RANGE,
            }
        )

        with no_materialized_columns():
            ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_trends_dau_person_property_filter_materialized(self):
        filter = Filter(
            data={
                "events": [{"id": "$pageview", "math": "dau"}],
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
    def track_funnel_normal(self):
        filter = Filter(
            data={
                "insight": "FUNNELS",
                "events": [{"id": "user signed up", "order": 0}, {"id": "insight analyzed", "order": 1}],
                **DATE_RANGE,
            },
            team=self.team,
        )
        ClickhouseFunnel(filter, self.team).run()

    @benchmark_clickhouse
    def track_correlations_by_events(self):
        filter = Filter(
            data={"events": [{"id": "user signed up"}, {"id": "insight analyzed"}], **SHORT_DATE_RANGE,},
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
                "properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
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
                "properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
                **DATE_RANGE,
            },
            team=self.team,
        )

        ClickhouseStickiness().run(filter, self.team)

    @benchmark_clickhouse
    def track_session_recordings_list(self):
        filter = SessionRecordingsFilter(data=SESSIONS_DATE_RANGE, team=self.team,)

        ClickhouseSessionRecordingList(filter, self.team).run()

    @benchmark_clickhouse
    def track_session_recordings_list_event_filter(self):
        filter = SessionRecordingsFilter(data={"events": [{"id": "$pageview"}], **SESSIONS_DATE_RANGE}, team=self.team,)

        ClickhouseSessionRecordingList(filter, self.team).run()

    @benchmark_clickhouse
    def track_session_recordings_list_person_property_filter(self):
        filter = SessionRecordingsFilter(
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
                    }
                ],
                **SESSIONS_DATE_RANGE,
            },
            team=self.team,
        )

        ClickhouseSessionRecordingList(filter, self.team).run()

    @benchmark_clickhouse
    def track_retention(self):
        filter = RetentionFilter(
            data={
                "insight": "RETENTION",
                "target_event": {"id": "$pageview"},
                "returning_event": {"id": "$pageview"},
                "total_intervals": 14,
                "retention_type": "retention_first_time",
                "period": "Week",
                **DATE_RANGE,
            },
            team=self.team,
        )

        ClickhouseRetention().run(filter, self.team)

    @benchmark_clickhouse
    def track_retention_with_person_breakdown(self):
        filter = RetentionFilter(
            data={
                "insight": "RETENTION",
                "target_event": {"id": "$pageview"},
                "returning_event": {"id": "$pageview"},
                "total_intervals": 14,
                "retention_type": "retention_first_time",
                "breakdown_type": "person",
                "breakdowns": [
                    {"type": "person", "property": "$browser"},
                    {"type": "person", "property": "$browser_version"},
                ],
                "period": "Week",
                **DATE_RANGE,
            },
            team=self.team,
        )

        with no_materialized_columns():
            ClickhouseRetention().run(filter, self.team)

    @benchmark_clickhouse
    def track_retention_filter_by_person_property(self):
        filter = RetentionFilter(
            data={
                "insight": "RETENTION",
                "target_event": {"id": "$pageview"},
                "returning_event": {"id": "$pageview"},
                "total_intervals": 14,
                "retention_type": "retention_first_time",
                "period": "Week",
                "properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
                **DATE_RANGE,
            },
            team=self.team,
        )

        with no_materialized_columns():
            ClickhouseRetention().run(filter, self.team)

    @benchmark_clickhouse
    def track_retention_filter_by_person_property_materialized(self):
        filter = RetentionFilter(
            data={
                "insight": "RETENTION",
                "target_event": {"id": "$pageview"},
                "returning_event": {"id": "$pageview"},
                "total_intervals": 14,
                "retention_type": "retention_first_time",
                "period": "Week",
                "properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
                **DATE_RANGE,
            },
            team=self.team,
        )

        ClickhouseRetention().run(filter, self.team)

    @benchmark_clickhouse
    def track_lifecycle(self):
        filter = Filter(
            data={
                "insight": "LIFECYCLE",
                "events": [{"id": "$pageview", "type": "events"}],
                "interval": "week",
                "shown_as": "Lifecycle",
                "date_from": "-14d",
                **DATE_RANGE,
            },
            team=self.team,
        )

        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_lifecycle_event_property_filter(self):
        filter = Filter(
            data={
                "insight": "LIFECYCLE",
                "events": [{"id": "$pageview", "type": "events"}],
                "interval": "week",
                "shown_as": "Lifecycle",
                "date_from": "-14d",
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
            },
            team=self.team,
        )

        with no_materialized_columns():
            ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_lifecycle_event_property_filter_materialized(self):
        filter = Filter(
            data={
                "insight": "LIFECYCLE",
                "events": [{"id": "$pageview", "type": "events"}],
                "interval": "week",
                "shown_as": "Lifecycle",
                "date_from": "-14d",
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
            },
            team=self.team,
        )

        ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_lifecycle_person_property_filter(self):
        filter = Filter(
            data={
                "insight": "LIFECYCLE",
                "events": [{"id": "$pageview", "type": "events"}],
                "interval": "week",
                "shown_as": "Lifecycle",
                "date_from": "-14d",
                "properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
                **DATE_RANGE,
            },
            team=self.team,
        )

        with no_materialized_columns():
            ClickhouseTrends().run(filter, self.team)

    @benchmark_clickhouse
    def track_lifecycle_person_property_filter_materialized(self):
        filter = Filter(
            data={
                "insight": "LIFECYCLE",
                "events": [{"id": "$pageview", "type": "events"}],
                "interval": "week",
                "shown_as": "Lifecycle",
                "date_from": "-14d",
                "properties": [{"key": "email", "operator": "icontains", "value": ".com", "type": "person"}],
                **DATE_RANGE,
            },
            team=self.team,
        )

        ClickhouseTrends().run(filter, self.team)

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
            cohort.calculate_people_ch(pending_version=0)
        self.cohort = cohort
