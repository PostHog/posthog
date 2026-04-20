from datetime import date
from decimal import Decimal
from typing import Any

from posthog.test.base import BaseTest

from posthog.schema import (
    DateRange,
    IntervalType,
    RevenueAnalyticsBreakdown,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsMRRQueryResultItem,
    RevenueAnalyticsTopCustomersGroupBy,
    RevenueAnalyticsTopCustomersQuery,
)

from .. import (
    RevenueAnalyticsGrossRevenueResultsFormatter,
    RevenueAnalyticsMetricsResultsFormatter,
    RevenueAnalyticsMRRResultsFormatter,
    RevenueAnalyticsTopCustomersResultsFormatter,
)


class TestRevenueAnalyticsFormatters(BaseTest):
    def test_format_gross_revenue(self):
        query = RevenueAnalyticsGrossRevenueQuery(
            dateRange=DateRange(date_from="2024-11-01", date_to="2025-02-01"),
            interval=IntervalType.MONTH,
            properties=[],
            breakdown=[RevenueAnalyticsBreakdown(property="revenue_analytics_product.name")],
        )
        results = [
            {
                "label": "stripe.posthog_test - Product F",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [Decimal("647.24355"), Decimal("2507.21839"), Decimal("2110.27254"), Decimal("2415.34023")],
            },
            {
                "label": "stripe.posthog_test - Product E",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [Decimal("64.243532"), Decimal("207.2432"), Decimal("210.272"), Decimal("415.3402")],
            },
        ]

        formatter = RevenueAnalyticsGrossRevenueResultsFormatter(query, results)
        self.assertEqual(
            formatter.format(),
            "Gross revenue for period: 2024-11-01 to 2025-02-01\n"
            "Breakdown by revenue_analytics_product.name\n"
            "Date|stripe.posthog_test - Product F|stripe.posthog_test - Product E\n"
            "2024-11-01|647.24355|64.24353\n"
            "2024-12-01|2507.21839|207.2432\n"
            "2025-01-01|2110.27254|210.272\n"
            "2025-02-01|2415.34023|415.3402",
        )

    def test_format_metrics(self):
        query = RevenueAnalyticsMetricsQuery(
            dateRange=DateRange(date_from="2024-11-01", date_to="2025-02-01"),
            interval=IntervalType.MONTH,
            properties=[],
            breakdown=[RevenueAnalyticsBreakdown(property="revenue_analytics_product.name")],
        )
        results: list[Any] = [
            {
                "label": "Subscription Count | stripe.posthog_test - Product E",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, 3, 6],
                "breakdown": {"property": "stripe.posthog_test - Product E", "kind": "Subscription Count"},
            },
            {
                "label": "New Subscription Count | stripe.posthog_test - Product E",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, 3, 3],
                "breakdown": {"property": "stripe.posthog_test - Product E", "kind": "New Subscription Count"},
            },
            {
                "label": "Churned Subscription Count | stripe.posthog_test - Product E",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, 0, 0],
                "breakdown": {"property": "stripe.posthog_test - Product E", "kind": "Churned Subscription Count"},
            },
            {
                "label": "Customer Count | stripe.posthog_test - Product E",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, 3, 6],
                "breakdown": {"property": "stripe.posthog_test - Product E", "kind": "Customer Count"},
            },
            {
                "label": "New Customer Count | stripe.posthog_test - Product E",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, 3, 3],
                "breakdown": {"property": "stripe.posthog_test - Product E", "kind": "New Customer Count"},
            },
            {
                "label": "Churned Customer Count | stripe.posthog_test - Product E",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, 0, 0],
                "breakdown": {"property": "stripe.posthog_test - Product E", "kind": "Churned Customer Count"},
            },
            {
                "label": "ARPU | stripe.posthog_test - Product E",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, Decimal("212.5129173366"), Decimal("277.5437136683")],
                "breakdown": {"property": "stripe.posthog_test - Product E", "kind": "ARPU"},
            },
            {
                "label": "LTV | stripe.posthog_test - Product E",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, None, None],
                "breakdown": {"property": "stripe.posthog_test - Product E", "kind": "LTV"},
            },
            {
                "label": "Subscription Count | stripe.posthog_test - Product F",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [1, 2, 3, 4],
                "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "Subscription Count"},
            },
            {
                "label": "New Subscription Count | stripe.posthog_test - Product F",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 1, 1, 2],
                "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "New Subscription Count"},
            },
            {
                "label": "Churned Subscription Count | stripe.posthog_test - Product F",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, 0, 1],
                "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "Churned Subscription Count"},
            },
            {
                "label": "Customer Count | stripe.posthog_test - Product F",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [1, 2, 3, 3],
                "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "Customer Count"},
            },
            {
                "label": "New Customer Count | stripe.posthog_test - Product F",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 1, 1, 1],
                "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "New Customer Count"},
            },
            {
                "label": "Churned Customer Count | stripe.posthog_test - Product F",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, 0, 1],
                "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "Churned Customer Count"},
            },
            {
                "label": "ARPU | stripe.posthog_test - Product F",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, Decimal("152.235"), Decimal("215.3234")],
                "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "ARPU"},
            },
            {
                "label": "LTV | stripe.posthog_test - Product F",
                "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                "data": [0, 0, None, None],
                "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "LTV"},
            },
        ]

        formatter = RevenueAnalyticsMetricsResultsFormatter(query, results)
        self.assertEqual(
            formatter.format(),
            "Revenue metrics for period: 2024-11-01 to 2025-02-01\n"
            "Breakdown by revenue_analytics_product.name\n"
            "\nSubscription Count\n"
            "Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F\n"
            "2024-11-01|0|1\n"
            "2024-12-01|0|2\n"
            "2025-01-01|3|3\n"
            "2025-02-01|6|4\n"
            "\nNew Subscription Count\n"
            "Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F\n"
            "2024-11-01|0|0\n"
            "2024-12-01|0|1\n"
            "2025-01-01|3|1\n"
            "2025-02-01|3|2\n"
            "\nChurned Subscription Count\n"
            "Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F\n"
            "2024-11-01|0|0\n"
            "2024-12-01|0|0\n"
            "2025-01-01|0|0\n"
            "2025-02-01|0|1\n"
            "\nCustomer Count\n"
            "Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F\n"
            "2024-11-01|0|1\n"
            "2024-12-01|0|2\n"
            "2025-01-01|3|3\n"
            "2025-02-01|6|3\n"
            "\nNew Customer Count\n"
            "Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F\n"
            "2024-11-01|0|0\n"
            "2024-12-01|0|1\n"
            "2025-01-01|3|1\n"
            "2025-02-01|3|1\n"
            "\nChurned Customer Count\n"
            "Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F\n"
            "2024-11-01|0|0\n"
            "2024-12-01|0|0\n"
            "2025-01-01|0|0\n"
            "2025-02-01|0|1\n"
            "\nARPU\n"
            "Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F\n"
            "2024-11-01|0|0\n"
            "2024-12-01|0|0\n"
            "2025-01-01|212.51292|152.235\n"
            "2025-02-01|277.54371|215.3234\n"
            "\nLTV\n"
            "Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F\n"
            "2024-11-01|0|0\n"
            "2024-12-01|0|0\n"
            "2025-01-01|N/A|N/A\n"
            "2025-02-01|N/A|N/A\n",
        )

    def test_format_mrr(self):
        query = RevenueAnalyticsMRRQuery(
            dateRange=DateRange(date_from="2024-11-01", date_to="2025-02-01"),
            interval=IntervalType.MONTH,
            properties=[],
            breakdown=[RevenueAnalyticsBreakdown(property="revenue_analytics_product.name")],
        )
        results = [
            RevenueAnalyticsMRRQueryResultItem(
                churn={
                    "breakdown": {"property": "stripe.posthog_test - Product C", "kind": "Churn"},
                    "data": [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")],
                    "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    "label": "Churn | stripe.posthog_test - Product C",
                    "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                },
                contraction={
                    "breakdown": {"property": "stripe.posthog_test - Product C", "kind": "Contraction"},
                    "data": [Decimal("0"), Decimal("-4.39147"), Decimal("-18.49837"), Decimal("0")],
                    "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    "label": "Contraction | stripe.posthog_test - Product C",
                    "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                },
                expansion={
                    "breakdown": {"property": "stripe.posthog_test - Product C", "kind": "Expansion"},
                    "data": [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("8.380455")],
                    "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    "label": "Expansion | stripe.posthog_test - Product C",
                    "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                },
                new={
                    "breakdown": {"property": "stripe.posthog_test - Product C", "kind": "New"},
                    "data": [Decimal("0"), Decimal("5.758325"), Decimal("18.59401"), Decimal("0")],
                    "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    "label": "New | stripe.posthog_test - Product C",
                    "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                },
                total={
                    "breakdown": {"property": "stripe.posthog_test - Product C", "kind": None},
                    "data": [Decimal("5.758325"), Decimal("24.352335"), Decimal("19.960865"), Decimal("9.84295")],
                    "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    "label": "stripe.posthog_test - Product C",
                    "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                },
            ),
            RevenueAnalyticsMRRQueryResultItem(
                churn={
                    "breakdown": {"property": "stripe.posthog_test - Product D", "kind": "Churn"},
                    "data": [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")],
                    "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    "label": "Churn | stripe.posthog_test - Product D",
                    "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                },
                contraction={
                    "breakdown": {"property": "stripe.posthog_test - Product D", "kind": "Contraction"},
                    "data": [Decimal("0"), Decimal("-45.391"), Decimal("-1.497"), Decimal("0")],
                    "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    "label": "Contraction | stripe.posthog_test - Product D",
                    "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                },
                expansion={
                    "breakdown": {"property": "stripe.posthog_test - Product D", "kind": "Expansion"},
                    "data": [Decimal("0"), Decimal("0"), Decimal("8.380455"), Decimal("25.12")],
                    "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    "label": "Expansion | stripe.posthog_test - Product D",
                    "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                },
                new={
                    "breakdown": {"property": "stripe.posthog_test - Product D", "kind": "New"},
                    "data": [Decimal("0"), Decimal("5.7325"), Decimal("18.01"), Decimal("0")],
                    "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    "label": "New | stripe.posthog_test - Product D",
                    "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                },
                total={
                    "breakdown": {"property": "stripe.posthog_test - Product D", "kind": None},
                    "data": [Decimal("5.325"), Decimal("4.335"), Decimal("19.865"), Decimal("19.845")],
                    "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    "label": "stripe.posthog_test - Product D",
                    "labels": ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025"],
                },
            ),
        ]

        formatter = RevenueAnalyticsMRRResultsFormatter(query, results)
        self.assertEqual(
            formatter.format(),
            "MRR metrics for period: 2024-11-01 to 2025-02-01\n"
            "Breakdown by revenue_analytics_product.name\n"
            "\nTotal MRR\n"
            "Date|stripe.posthog_test - Product C|stripe.posthog_test - Product D\n"
            "2024-11-30|5.75833|5.325\n"
            "2024-12-31|24.35234|4.335\n"
            "2025-01-31|19.96086|19.865\n"
            "2025-02-28|9.84295|19.845\n"
            "\nNew MRR\n"
            "Date|stripe.posthog_test - Product C|stripe.posthog_test - Product D\n"
            "2024-11-30|0|0\n"
            "2024-12-31|5.75833|5.7325\n"
            "2025-01-31|18.59401|18.01\n"
            "2025-02-28|0|0\n"
            "\nExpansion MRR\n"
            "Date|stripe.posthog_test - Product C|stripe.posthog_test - Product D\n"
            "2024-11-30|0|0\n"
            "2024-12-31|0|0\n"
            "2025-01-31|0|8.38045\n"
            "2025-02-28|8.38045|25.12\n"
            "\nContraction MRR\n"
            "Date|stripe.posthog_test - Product C|stripe.posthog_test - Product D\n"
            "2024-11-30|0|0\n"
            "2024-12-31|-4.39147|-45.391\n"
            "2025-01-31|-18.49837|-1.497\n"
            "2025-02-28|0|0\n"
            "\nChurned MRR\n"
            "Date|stripe.posthog_test - Product C|stripe.posthog_test - Product D\n"
            "2024-11-30|0|0\n"
            "2024-12-31|0|0\n"
            "2025-01-31|0|0\n"
            "2025-02-28|0|0\n",
        )

    def test_format_top_customers_group_by_month(self):
        query = RevenueAnalyticsTopCustomersQuery(
            dateRange=DateRange(date_from="2024-11-01", date_to="2025-02-01"),
            groupBy=RevenueAnalyticsTopCustomersGroupBy.MONTH,
            properties=[],
        )
        results = [
            ("cus_5", "John Doe Jr", Decimal("1105.82156"), date(2025, 2, 1)),
            ("cus_6", "John Doe Jr Jr", Decimal("668.67503"), date(2025, 2, 1)),
            ("cus_3", "John Smith", Decimal("615.997315"), date(2025, 2, 1)),
            ("cus_4", "Jane Smith", Decimal("85.47825"), date(2025, 2, 1)),
            ("cus_2", "Jane Doe", Decimal("26.0100949999"), date(2025, 2, 1)),
            ("cus_1", "John Doe", Decimal("5.2361453433"), date(2025, 2, 1)),
            ("cus_5", "John Doe Jr", Decimal("8104.56"), date(2025, 3, 1)),
            ("cus_6", "John Doe Jr Jr", Decimal("864.03"), date(2025, 3, 1)),
            ("cus_3", "John Smith", Decimal("814.915"), date(2025, 3, 1)),
            ("cus_4", "Jane Smith", Decimal("84.25"), date(2025, 3, 1)),
            ("cus_2", "Jane Doe", Decimal("84.0100999"), date(2025, 3, 1)),
            ("cus_1", "John Doe", Decimal("73.2361433"), date(2025, 3, 1)),
        ]

        formatter = RevenueAnalyticsTopCustomersResultsFormatter(query, results)
        self.assertEqual(
            formatter.format(),
            "Top customers for period: 2024-11-01 to 2025-02-01\n"
            "Grouped by month\n"
            "Customer Name|2025-02-01|2025-03-01\n"
            "John Doe Jr|1105.82156|8104.56\n"
            "John Doe Jr Jr|668.67503|864.03\n"
            "John Smith|615.99731|814.915\n"
            "Jane Smith|85.47825|84.25\n"
            "Jane Doe|26.01009|84.0101\n"
            "John Doe|5.23615|73.23614",
        )

    def test_format_top_customers_group_by_all(self):
        query = RevenueAnalyticsTopCustomersQuery(
            dateRange=DateRange(date_from="2024-11-01", date_to="2025-02-01"),
            groupBy=RevenueAnalyticsTopCustomersGroupBy.ALL,
            properties=[],
        )
        results = [
            ("cus_5", "John Doe Jr", Decimal("1105.82156"), "all"),
            ("cus_6", "John Doe Jr Jr", Decimal("668.67503"), "all"),
            ("cus_3", "John Smith", Decimal("615.997315"), "all"),
            ("cus_4", "Jane Smith", Decimal("85.47825"), "all"),
            ("cus_2", "Jane Doe", Decimal("26.0100949999"), "all"),
            ("cus_1", "John Doe", Decimal("5.2361453433"), "all"),
        ]

        formatter = RevenueAnalyticsTopCustomersResultsFormatter(query, results)
        self.assertEqual(
            formatter.format(),
            "Top customers for period: 2024-11-01 to 2025-02-01\n"
            "Customer Name|Revenue\n"
            "John Doe Jr|1105.82156\n"
            "John Doe Jr Jr|668.67503\n"
            "John Smith|615.99731\n"
            "Jane Smith|85.47825\n"
            "Jane Doe|26.01009\n"
            "John Doe|5.23615",
        )
