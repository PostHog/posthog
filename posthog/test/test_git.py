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
            (
                "actions_run_url",
                "is this flaky? https://github.com/posthog/posthog/actions/runs/30560492835/job/90936416640",
                "posthog/posthog",
            ),
            (
                "slack_wrapped_actions_url_with_label",
                "why did this fail? <https://github.com/posthog/posthog-js/actions/runs/29764624536|"
                "github.com/posthog/posthog-js/…/29764624536>",
                "posthog/posthog-js",
            ),
            ("clone_url_suffix", "cloned from git@github.com:posthog/posthog.git", "posthog/posthog"),
            ("unconnected_repo_url", "see https://github.com/acme/widgets/pull/1", None),
            ("lookalike_host", "see https://mygithub.com/posthog/posthog/pull/1", None),
            ("host_prefix_spoof", "see https://github.com.evil.tld/posthog/posthog", None),
            (
                "bare_token_beats_later_url",
                "fix posthog/posthog-js — context: https://github.com/posthog/posthog/pull/1",
                "posthog/posthog-js",
            ),
            (
                "two_linked_repos_is_ambiguous",
                "https://github.com/posthog/posthog/pull/1 broke https://github.com/posthog/posthog-js/actions/runs/2",
                None,
            ),
            (
                "same_repo_linked_twice_is_not_ambiguous",
                "https://github.com/posthog/posthog/pull/1 and https://github.com/posthog/posthog/actions/runs/2",
                "posthog/posthog",
            ),
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
