from django.test.testcases import SimpleTestCase

from parameterized import parameterized

from posthog.session_recordings.session_recording_api import clean_referer_url


class TestCleanRefererUrl(SimpleTestCase):
    @parameterized.expand(
        [
            ("https://example.com/project/1234/", "unknown"),
            ("https://example.com/person/jyotioffice97%40gmail.com", "person-page"),
            ("https://example.com/person/0194b243-f190-7596-9728-ab2a083dd0e5", "person-page"),
            ("https://example.com/insights/CrKMPO8s", "insight"),
            ("https://example.com/insights/CrKMPO8s/edit", "insight-edit"),
            (
                "https://example.com/data-management/events/01889c68-25d0-0000-a461-98a360fe816e",
                "data-management-events",
            ),
            ("https://sub.example.com/person/fulmvero%40gmail.com", "person-page"),
            ("http://another-site.com/insights/new", "insight"),
            ("/project/5678", "unknown"),  # Case: No domain, direct path
            ("/person/random-name", "person-page"),  # Non-email person
            ("/insights/ABC123/edit", "insight-edit"),  # Insights edit
            ("/insights/ABC123", "insight"),  # Insights general case
            ("", "unknown"),
            (None, "unknown"),
            ("/replay/0194a8c7-8477-7952-80d1-04288c62daf5", "replay-direct"),
            ("/replay/playlists/", "replay-playlists"),
            ("https://us.posthog.com/project/2/replay/playlists/UeykLhgA", "replay-playlists-direct"),
        ]
    )
    def test_cleaning_referer_url(self, referer_url: str | None, expected_output: str) -> None:
        assert clean_referer_url(referer_url) == expected_output
