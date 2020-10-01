from django.test import TestCase

from posthog.templatetags.posthog_assets import utmify_email_url
from posthog.templatetags.posthog_filters import compact_number, percentage


class TestTemplateTags(TestCase):
    def test_utmify_email_url(self):
        self.assertEqual(
            utmify_email_url("https://posthog.com", "email_one"),
            "https://posthog.com?utm_source=posthog&utm_medium=email&utm_campaign=email_one",
        )

        self.assertEqual(
            utmify_email_url("https://posthog.com?qs=a", "email_two"),
            "https://posthog.com?qs=a&utm_source=posthog&utm_medium=email&utm_campaign=email_two",
        )

    def test_compact_number(self):
        self.assertEqual(compact_number(5001), "5K")
        self.assertEqual(compact_number(5312), "5.3K")
        self.assertEqual(compact_number(5392), "5.3K")  # rounds down
        self.assertEqual(compact_number(2833102, 2), "2.83M")
        self.assertEqual(compact_number(8283310234), "8.2B")

    def test_percentage(self):
        self.assertEqual(percentage(0.1829348, 2), "18.29%")
        self.assertEqual(percentage(0.7829, 1), "78.3%")
