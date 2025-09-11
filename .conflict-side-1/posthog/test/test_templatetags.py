from django.test import TestCase

from posthog.templatetags.posthog_filters import compact_number, percentage


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
