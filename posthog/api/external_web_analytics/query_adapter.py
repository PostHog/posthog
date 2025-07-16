from datetime import date, datetime
from typing import Optional, Any

from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.schema import (
    WebOverviewQuery,
    DateRange,
    HogQLQueryModifiers,
    EventPropertyFilter,
    PropertyOperator,
    WebOverviewQueryResponse,
)
from posthog.models import Team
from posthog.api.external_web_analytics.serializers import WebAnalyticsOverviewRequestSerializer


class ExternalWebAnalyticsQueryAdapter:
    """
    Adapter that uses the internal WebOverviewQueryRunner to provide data for the external API.
    It tries to separate the web analytics query runners from the external API.
    """

    def __init__(self, team: Team):
        self.team = team

    def _get_base_properties(self, domain: Optional[str] = None) -> list[EventPropertyFilter]:
        properties = []
        if domain:
            properties.append(
                EventPropertyFilter(
                    key="$host",
                    operator=PropertyOperator.EXACT,
                    value=[domain],
                )
            )
        return properties

    def _get_datetime_str(self, date_value: date | datetime) -> str:
        return date_value.strftime("%Y-%m-%d")

    def _get_default_modifiers(self) -> HogQLQueryModifiers:
        return HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=True,
            convertToProjectTimezone=True,
        )

    def get_overview_data(self, serializer: WebAnalyticsOverviewRequestSerializer) -> dict[str, Any]:
        data = serializer.validated_data

        query = WebOverviewQuery(
            kind="WebOverviewQuery",
            dateRange=DateRange(
                date_from=self._get_datetime_str(data["date_from"]),
                date_to=self._get_datetime_str(data["date_to"]),
            ),
            properties=self._get_base_properties(data.get("domain")),
            filterTestAccounts=data.get("filter_test_accounts", True),
            doPathCleaning=data.get("do_path_cleaning", True),
            includeRevenue=False,
        )

        runner = WebOverviewQueryRunner(
            query=query,
            team=self.team,
            modifiers=self._get_default_modifiers(),
        )

        response = runner.calculate()

        return self._transform_overview_response(response)

    def _transform_overview_response(self, response: WebOverviewQueryResponse) -> dict[str, Any]:
        """
        Transform the internal WebOverviewQueryResponse to external API format.

        Internal format has results as list of dicts with keys like:
        [
            {"key": "visitors", "value": 1234, ...},
            {"key": "views", "value": 5678, ...},
            ...
        ]

        External format expects:
        {
            "visitors": 1234,
            "views": 5678,
            "sessions": 901,
            "bounce_rate": 0.45,
            "session_duration": 123.4
        }
        """

        metric_mappings = {
            "visitors": ("visitors", lambda v: int(v) if v is not None else 0),
            "views": ("views", lambda v: int(v) if v is not None else 0),
            "sessions": ("sessions", lambda v: int(v) if v is not None else 0),
            "bounce rate": ("bounce_rate", lambda v: (v / 100.0) if v is not None else 0.0),
            "session duration": ("session_duration", lambda v: float(v) if v is not None else 0.0),
        }

        result_dict = {}
        for result in response.results:
            if result.key in metric_mappings:
                external_key, transformer = metric_mappings[result.key]
                result_dict[external_key] = transformer(result.value)

        return {
            "visitors": result_dict.get("visitors", 0),
            "views": result_dict.get("views", 0),
            "sessions": result_dict.get("sessions", 0),
            "bounce_rate": result_dict.get("bounce_rate", 0.0),
            "session_duration": result_dict.get("session_duration", 0.0),
        }
