from datetime import timedelta

from posthog.client import sync_execute
from posthog.models.app_metrics.sql import QUERY_APP_METRICS_TIME_SERIES
from posthog.models.filters.mixins.base import IntervalType
from posthog.models.team.team import Team
from posthog.queries.app_metrics.serializers import AppMetricsRequestSerializer
from posthog.queries.query_date_range import QueryDateRange


class AppMetricsQuery:
    def __init__(self, team: Team, plugin_config_id: int, filter: AppMetricsRequestSerializer):
        self.team = team
        self.plugin_config_id = plugin_config_id
        self.filter = filter

        self.query_date_range = QueryDateRange(filter=self.filter, team=self.team)

    def run(self):
        query, params = self.metrics_query()
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

    def metrics_query(self):
        job_id = self.filter.validated_data.get("job_id")
        query = QUERY_APP_METRICS_TIME_SERIES.format(
            job_id_clause="AND job_id = %(job_id)s" if job_id is not None else "",
            interval_function=self.interval_function,
        )

        return query, {
            "team_id": self.team.pk,
            "plugin_config_id": self.plugin_config_id,
            "category": self.filter.validated_data.get("category"),
            "job_id": job_id,
            "date_from": self.date_from.strftime("%Y-%m-%d %H:%M:%S"),
            "date_to": self.date_to.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": self.team.timezone,
            "interval": self.interval,
        }

    @property
    def date_from(self):
        return self.query_date_range.date_from_param

    @property
    def date_to(self):
        return self.query_date_range.date_to_param

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
