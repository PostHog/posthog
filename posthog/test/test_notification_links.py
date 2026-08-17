from urllib.parse import parse_qs, urlparse

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.notification_links import tag_notification_url


class TestTagNotificationUrl(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_query", "https://app.posthog.com/project/2/inbox/reports/abc"),
            ("existing_query", "https://app.posthog.com/project/2/inbox/reports/abc?tab=pulls"),
        ]
    )
    def test_tagging_preserves_the_original_link(self, _name, url):
        tagged = tag_notification_url(url, source="slack", surface="inbox_card_team", notification_id="n-1")

        original = urlparse(url)
        parsed = urlparse(tagged)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path), (original.scheme, original.netloc, original.path))
        params = parse_qs(parsed.query)
        self.assertEqual(params["utm_source"], ["slack"])
        self.assertEqual(params["utm_medium"], ["notification"])
        self.assertEqual(params["utm_content"], ["inbox_card_team"])
        self.assertEqual(params["nid"], ["n-1"])
        for key, value in parse_qs(original.query).items():
            self.assertEqual(params[key], value)

    def test_link_without_a_send_carries_no_notification_id(self):
        # The PR footer link is written once and read by whoever opens the PR, so a send id on it
        # would attribute every later click to one imaginary send.
        tagged = tag_notification_url("https://app.posthog.com/x", source="github", surface="pr_footer")

        params = parse_qs(urlparse(tagged).query)
        self.assertNotIn("nid", params)
        self.assertEqual(params["utm_source"], ["github"])
