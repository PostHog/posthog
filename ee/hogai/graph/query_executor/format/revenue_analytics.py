from typing import Any

from posthog.schema import (
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsMRRQueryResultItem,
    RevenueAnalyticsTopCustomersGroupBy,
    RevenueAnalyticsTopCustomersQuery,
)

from products.revenue_analytics.backend.hogql_queries.revenue_analytics_metrics_query_runner import (
    KINDS as METRICS_KINDS,
)

from .utils import format_date, format_matrix, format_number, strip_datetime_seconds


class RevenueAnalyticsGrossRevenueResultsFormatter:
    """
    Compresses and formats revenue analytics gross revenue results into a LLM-friendly string.
    """

    def __init__(
        self,
        query: RevenueAnalyticsGrossRevenueQuery,
        results: list[dict[str, Any]],
    ):
        self._query = query
        self._results = results

    def format(self) -> str:
        results = self._results
        if len(results) == 0:
            return "No data recorded for this time period."

        breakdown_properties = [breakdown.property for breakdown in self._query.breakdown]

        date_from = self._query.dateRange.date_from if self._query.dateRange else "start of time"
        date_to = self._query.dateRange.date_to if self._query.dateRange else "end of time"
        header = f"Gross revenue for period: {date_from} to {date_to}\n"
        breakdown = f"Breakdown by {', '.join(breakdown_properties)}\n" if len(breakdown_properties) > 0 else ""

        return f"{header}{breakdown}{self._format_results(results)}"

    def _format_results(self, results: list[dict[str, Any]]) -> str:
        # Get dates and series labels
        result = results[0]
        dates = result["days"]

        matrix: list[list[str]] = [
            # Header row
            ["Date", *[series["label"] for series in results]],
            # Data rows
            *[
                [strip_datetime_seconds(date), *[format_number(series["data"][i]) for series in results]]
                for i, date in enumerate(dates)
            ],
        ]

        return format_matrix(matrix)


class RevenueAnalyticsMetricsResultsFormatter:
    """
    Compresses and formats revenue analytics metrics results into a LLM-friendly string.
    """

    def __init__(
        self,
        query: RevenueAnalyticsMetricsQuery,
        results: list[dict[str, Any]],
    ):
        self._query = query
        self._results = results

    def format(self) -> str:
        results = self._results
        if len(results) == 0:
            return "No data recorded for this time period."

        breakdown_properties = [breakdown.property for breakdown in self._query.breakdown]

        date_from = self._query.dateRange.date_from if self._query.dateRange else "start of time"
        date_to = self._query.dateRange.date_to if self._query.dateRange else "end of time"
        header = f"Revenue metrics for period: {date_from} to {date_to}\n"
        breakdown = f"Breakdown by {', '.join(breakdown_properties)}\n" if len(breakdown_properties) > 0 else ""

        return f"{header}{breakdown}{self._format_results(results)}"

    def _format_results(self, results: list[dict[str, Any]]) -> str:
        # Get dates and series labels
        result = results[0]
        dates = result["days"]

        content = ""
        for kind in METRICS_KINDS:
            kind_series = self._extract_series(results, kind)

            header = ["Date", *[series["breakdown"]["property"] for series in kind_series]]
            matrix: list[list[str]] = [
                header,
                *[
                    [strip_datetime_seconds(date), *[format_number(series["data"][i]) for series in kind_series]]
                    for i, date in enumerate(dates)
                ],
            ]

            content += f"\n{kind}\n{format_matrix(matrix)}\n"

        return content

    def _extract_series(self, results: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        return [result for result in results if result["breakdown"]["kind"] == kind]


class RevenueAnalyticsMRRResultsFormatter:
    """
    Compresses and formats revenue analytics MRR results into a LLM-friendly string.
    """

    def __init__(self, query: RevenueAnalyticsMRRQuery, results: list[RevenueAnalyticsMRRQueryResultItem]):
        self._query = query
        self._results = results

    def format(self) -> str:
        results = self._results
        if len(results) == 0:
            return "No data recorded for this time period."

        breakdown_properties = [breakdown.property for breakdown in self._query.breakdown]

        date_from = self._query.dateRange.date_from if self._query.dateRange else "start of time"
        date_to = self._query.dateRange.date_to if self._query.dateRange else "end of time"
        header = f"MRR metrics for period: {date_from} to {date_to}\n"
        breakdown = f"Breakdown by {', '.join(breakdown_properties)}\n" if len(breakdown_properties) > 0 else ""

        return f"{header}{breakdown}{self._format_results(results)}"

    def _format_results(self, results: list[RevenueAnalyticsMRRQueryResultItem]) -> str:
        # Get dates and series labels
        result = results[0]
        dates = result.total["days"]

        content = ""
        for key, label in [
            ("total", "Total"),
            ("new", "New"),
            ("expansion", "Expansion"),
            ("contraction", "Contraction"),
            ("churn", "Churned"),
        ]:
            key_series = self._extract_series(results, key)

            header = ["Date", *[series["breakdown"]["property"] for series in key_series]]
            matrix: list[list[str]] = [
                header,
                *[
                    [strip_datetime_seconds(date), *[format_number(series["data"][i]) for series in key_series]]
                    for i, date in enumerate(dates)
                ],
            ]

            content += f"\n{label} MRR\n{format_matrix(matrix)}\n"

        return content

    def _extract_series(self, results: list[RevenueAnalyticsMRRQueryResultItem], key: str) -> list[dict[str, Any]]:
        return [result.model_dump()[key] for result in results]


class RevenueAnalyticsTopCustomersResultsFormatter:
    """
    Compresses and formats revenue analytics top customers results into a LLM-friendly string.
    """

    def __init__(self, query: RevenueAnalyticsTopCustomersQuery, results: list[Any]):
        self._query = query
        self._results = results

    # Results is a list of tuples (customer_id, customer_name, revenue, month)
    def format(self) -> str:
        results = self._results
        if len(results) == 0:
            return "No data recorded for this time period."

        date_from = self._query.dateRange.date_from if self._query.dateRange else "start of time"
        date_to = self._query.dateRange.date_to if self._query.dateRange else "end of time"
        header = f"Top customers for period: {date_from} to {date_to}\n"

        if self._query.groupBy == RevenueAnalyticsTopCustomersGroupBy.MONTH:
            return f"{header}Grouped by month\n{self._format_results_by_month(results)}"

        return f"{header}{self._format_results_all(results)}"

    def _format_results_by_month(self, results: list[Any]) -> str:
        # Display customers with higher revenue first
        sorted_by_revenue = sorted(results, key=lambda x: x[2], reverse=True)
        customers = list(dict.fromkeys(result[1] for result in sorted_by_revenue))
        dates = list(dict.fromkeys([result[3] for result in sorted_by_revenue]))
        grouped_by_date_and_customer = {
            date: {
                customer_name: revenue
                for _, customer_name, revenue, inner_date in sorted_by_revenue
                if inner_date == date
            }
            for date in dates
        }

        matrix: list[list[str]] = [
            ["Customer Name", *[format_date(date) for date in sorted(dates)]],
        ]
        for customer in customers:
            matrix.append(
                [
                    customer,
                    *[
                        format_number(grouped_by_date_and_customer.get(date, {}).get(customer, 0))
                        for date in sorted(dates)
                    ],
                ]
            )

        return format_matrix(matrix)

    def _format_results_all(self, results: list[Any]) -> str:
        matrix: list[list[str]] = [
            ["Customer Name", "Revenue"],
            *[[result[1], format_number(result[2])] for result in results],
        ]

        return format_matrix(matrix)
