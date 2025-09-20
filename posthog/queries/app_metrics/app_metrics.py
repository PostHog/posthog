import json
from datetime import datetime, timedelta

from django.utils.timezone import now

from posthog.clickhouse.client import sync_execute
from posthog.models.app_metrics.sql import (
    QUERY_APP_METRICS_DELIVERY_RATE,
    QUERY_APP_METRICS_ERROR_DETAILS,
    QUERY_APP_METRICS_ERRORS,
    QUERY_APP_METRICS_TIME_SERIES,
)
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.models.filters.mixins.base import IntervalType
from posthog.models.team.team import Team
from posthog.queries.app_metrics.serializers import AppMetricsErrorsRequestSerializer, AppMetricsRequestSerializer
from posthog.queries.util import format_ch_timestamp
from posthog.utils import relative_date_parse


class TeamPluginsDeliveryRateQuery:
    QUERY = QUERY_APP_METRICS_DELIVERY_RATE

    def __init__(self, team: Team):
        self.team = team

    def run(self):
        results = sync_execute(
            self.QUERY,
            {
                "team_id": self.team.pk,
                "from_date": format_clickhouse_timestamp(datetime.now() - timedelta(hours=24)),
            },
        )
        return dict(results)


class AppMetricsQuery:
    QUERY = QUERY_APP_METRICS_TIME_SERIES

    def __init__(self, team: Team, plugin_config_id: int, filter: AppMetricsRequestSerializer):
        self.team = team
        self.plugin_config_id = plugin_config_id
        self.filter = filter

    def run(self):
        query, params = self.query()
        dates, successes, successes_on_retry, failures = sync_execute(query, params)[0]
        return {
            "dates": [
                timestamp.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if self.interval == "hour" else ""))
                for timestamp in dates
            ],
            "successes": successes,
            "successes_on_retry": successes_on_retry,
            "failures": failures,
            "totals": {
                "successes": sum(successes),
                "successes_on_retry": sum(successes_on_retry),
                "failures": sum(failures),
            },
        }

    def query(self):
        job_id = self.filter.validated_data.get("job_id")
        category = self.filter.validated_data.get("category")
        query = self.QUERY.format(
            job_id_clause="AND job_id = %(job_id)s" if job_id is not None else "",
            category_clause="AND category = %(category)s" if category is not None else "",
            interval_function=self.interval_function,
        )

        return query, {
            "team_id": self.team.pk,
            "plugin_config_id": self.plugin_config_id,
            "category": category,
            "job_id": job_id,
            "date_from": format_ch_timestamp(self.date_from),
            "date_to": format_ch_timestamp(self.date_to),
            "timezone": self.team.timezone,
            "interval": self.interval,
        }

    @property
    def date_from(self):
        return relative_date_parse(
            self.filter.validated_data.get("date_from"),
            self.team.timezone_info,
            always_truncate=True,
        )

    @property
    def date_to(self):
        date_to_string = self.filter.validated_data.get("date_to")
        return (
            relative_date_parse(date_to_string, self.team.timezone_info, always_truncate=True)
            if date_to_string is not None
            else now()
        )

    @property
    def interval(self) -> IntervalType:
        if self.date_to - self.date_from < timedelta(days=2):
            return "hour"
        else:
            return "day"

    @property
    def interval_function(self):
        if self.interval == "day":
            return "toIntervalDay"
        else:
            return "toIntervalHour"


class AppMetricsErrorsQuery(AppMetricsQuery):
    QUERY = QUERY_APP_METRICS_ERRORS
    KEYS = ("error_type", "count", "last_seen")

    def run(self):
        query, params = self.query()
        results = sync_execute(query, params)

        return [dict(zip(self.KEYS, row)) for row in results]


class AppMetricsErrorDetailsQuery:
    QUERY = QUERY_APP_METRICS_ERROR_DETAILS

    def __init__(
        self,
        team: Team,
        plugin_config_id: int,
        filter: AppMetricsErrorsRequestSerializer,
    ):
        self.team = team
        self.plugin_config_id = plugin_config_id
        self.filter = filter

    def run(self):
        query, params = self.query()
        return list(map(self._parse_row, sync_execute(query, params)))

    def query(self):
        job_id = self.filter.validated_data.get("job_id")
        category = self.filter.validated_data.get("category")
        query = self.QUERY.format(
            job_id_clause="AND job_id = %(job_id)s" if job_id is not None else "",
            category_clause="AND category = %(category)s" if category is not None else "",
        )

        return query, {
            "team_id": self.team.pk,
            "plugin_config_id": self.plugin_config_id,
            "category": category,
            "job_id": job_id,
            "error_type": self.filter.validated_data.get("error_type"),
        }

    def _parse_row(self, row):
        timestamp, error_uuid, error_type, error_details = row
        return {
            "timestamp": timestamp,
            "error_uuid": error_uuid,
            "error_type": error_type,
            "error_details": json.loads(error_details),
        }
