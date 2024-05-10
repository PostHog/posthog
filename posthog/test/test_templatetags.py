from django.test import TestCase

from posthog.templatetags.posthog_filters import compact_number, humanize_time_diff, percentage


class TestTemplateTags(TestCase):
    def test_compact_number(self):
        self.assertEqual(compact_number(5001), "5K")
        self.assertEqual(compact_number(5312), "5.31K")
        self.assertEqual(compact_number(5392), "5.39K")
        self.assertEqual(compact_number(2833102), "2.83M")
        self.assertEqual(compact_number(8283310234), "8.28B")

    def test_percentage(self):
        self.assertEqual(percentage(0.1829348, 2), "18.29%")
        self.assertEqual(percentage(0.7829, 1), "78.3%")

    def test_humanize_time_diff(self):
        self.assertEqual(humanize_time_diff("2023-01-10", "2024-10-05"), "1 year")
        self.assertEqual(humanize_time_diff("2022-01-01", "2024-10-01"), "2 years")
        self.assertEqual(humanize_time_diff("2024-01-01", "2024-10-25"), "9 months")
        self.assertEqual(humanize_time_diff("2024-01-01", "2024-02-01"), "1 month")
        self.assertEqual(humanize_time_diff("2024-01-01", "2024-01-05"), "4 days")
        self.assertEqual(humanize_time_diff("2024-01-01", "2024-01-02"), "1 day")
        self.assertEqual(humanize_time_diff("2022-01-01 00:00:00", "2022-01-01 05:00:00"), "5 hours")
        self.assertEqual(humanize_time_diff("2022-01-01 00:00:00", "2022-01-01 01:00:00"), "1 hour")
        self.assertEqual(humanize_time_diff("2022-01-01 00:00:00", "2022-01-01 00:20:00"), "1 hour")
