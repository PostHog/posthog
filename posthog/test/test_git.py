from parameterized import parameterized

from posthog.git import extract_explicit_repo

REPOS = ["posthog/posthog", "posthog/posthog-js", "posthog/posthog.com"]


class TestExtractExplicitRepo:
    @parameterized.expand(
        [
            ("bare_token", "please fix posthog/posthog-js now", "posthog/posthog-js"),
            ("case_insensitive", "look at PostHog/PostHog-JS", "posthog/posthog-js"),
            ("dotted_repo_name", "the posthog/posthog.com site is slow", "posthog/posthog.com"),
            ("surrounding_punctuation", "is it in `posthog/posthog`?", "posthog/posthog"),
            (
                "slack_link_label",
                "see <https://github.com/posthog/posthog-js|posthog/posthog-js>",
                "posthog/posthog-js",
            ),
            ("no_repo_token", "the dashboards are slow", None),
            ("unconnected_repo", "fix acme/widgets please", None),
            ("bare_url_ignored", "https://posthog.com/posthog is down", None),
        ]
    )
    def test_extracts_matching_repo(self, _name: str, text: str, expected: str | None):
        assert extract_explicit_repo(text, REPOS) == expected

    @parameterized.expand(
        [
            ("empty_text", "", REPOS),
            ("empty_repo_list", "posthog/posthog", []),
        ]
    )
    def test_returns_none_on_empty_inputs(self, _name: str, text: str, repos: list[str]):
        assert extract_explicit_repo(text, repos) is None
