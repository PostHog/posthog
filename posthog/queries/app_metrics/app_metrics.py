from django.utils.timezone import now

from posthog.client import sync_execute
from posthog.models.app_metrics.sql import QUERY_APP_METRICS_TIME_SERIES
from posthog.models.team.team import Team
from posthog.queries.app_metrics.serializers import AppMetricsRequestSerializer
from posthog.queries.util import format_ch_timestamp
from posthog.utils import relative_date_parse


class AppMetricsQuery:
    def __init__(self, team: Team, plugin_config_id: int, filter: AppMetricsRequestSerializer):
        self.team = team
        self.plugin_config_id = plugin_config_id
        self.filter = filter

    def run(self):
        query, params = self.metrics_query()
        dates, successes, successes_on_retry, failures = sync_execute(query, params)[0]
        return {
            "dates": [timestamp.strftime("%Y-%m-%d") for timestamp in dates],
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
            job_id_clause="AND job_id = %(job_id)s" if job_id is not None else ""
        )

        return query, {
            "team_id": self.team.pk,
            "plugin_config_id": self.plugin_config_id,
            "category": self.filter.validated_data.get("category"),
            "job_id": job_id,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "timezone": self.team.timezone,
        }

    @property
    def date_from(self):
        datetime = relative_date_parse(self.filter.validated_data.get("date_from"))
        return format_ch_timestamp(datetime, convert_to_timezone=self.team.timezone)

    @property
    def date_to(self):
        date_to_string = self.filter.validated_data.get("date_to")
        datetime = relative_date_parse(date_to_string) if date_to_string is not None else now()
        return format_ch_timestamp(datetime, convert_to_timezone=self.team.timezone)
