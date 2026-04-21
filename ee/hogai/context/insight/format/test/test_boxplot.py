from unittest import TestCase

from parameterized import parameterized

from .. import BoxPlotResultsFormatter


class TestBoxPlotResultsFormatter(TestCase):
    @parameterized.expand(
        [
            (
                "single_series",
                [
                    {
                        "day": "2025-01-20",
                        "label": "Day 1",
                        "min": 1.2,
                        "p25": 5.5,
                        "median": 12.3,
                        "p75": 25.8,
                        "max": 100.4,
                        "mean": 18.7,
                        "series_label": "$pageview",
                        "series_index": 0,
                    },
                    {
                        "day": "2025-01-21",
                        "label": "Day 2",
                        "min": 0.8,
                        "p25": 4.2,
                        "median": 10.1,
                        "p75": 22.5,
                        "max": 95.2,
                        "mean": 16.3,
                        "series_label": "$pageview",
                        "series_index": 0,
                    },
                ],
                "Date|Min|P25|Median|P75|Max|Mean\n2025-01-20|1.2|5.5|12.3|25.8|100.4|18.7\n2025-01-21|0.8|4.2|10.1|22.5|95.2|16.3",
            ),
            (
                "multiple_series",
                [
                    {
                        "day": "2025-01-20",
                        "label": "Day 1",
                        "min": 1.0,
                        "p25": 5.0,
                        "median": 10.0,
                        "p75": 20.0,
                        "max": 50.0,
                        "mean": 15.0,
                        "series_label": "$pageview",
                        "series_index": 0,
                    },
                    {
                        "day": "2025-01-20",
                        "label": "Day 1",
                        "min": 2.0,
                        "p25": 8.0,
                        "median": 15.0,
                        "p75": 30.0,
                        "max": 80.0,
                        "mean": 22.0,
                        "series_label": "signup",
                        "series_index": 1,
                    },
                ],
                "Date|Series|Min|P25|Median|P75|Max|Mean\n2025-01-20|$pageview|1|5|10|20|50|15\n2025-01-20|signup|2|8|15|30|80|22",
            ),
            (
                "empty",
                [],
                "No data recorded for this time period.",
            ),
            (
                "integer_values",
                [
                    {
                        "day": "2025-01-20",
                        "label": "Day 1",
                        "min": 0.0,
                        "p25": 0.0,
                        "median": 0.0,
                        "p75": 0.0,
                        "max": 0.0,
                        "mean": 0.0,
                        "series_label": "$pageview",
                        "series_index": 0,
                    },
                ],
                "Date|Min|P25|Median|P75|Max|Mean\n2025-01-20|0|0|0|0|0|0",
            ),
        ]
    )
    def test_boxplot_format(self, _name: str, data: list, expected: str):
        self.assertEqual(BoxPlotResultsFormatter(data).format(), expected)
