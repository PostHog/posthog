from parameterized import parameterized

from posthog.git import extract_explicit_repo, extract_linked_repo, extract_repo_from_scopes

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
            ("github_url_is_not_a_typed_token", "see https://github.com/posthog/posthog/pull/1", None),
            ("two_bare_tokens_first_wins", "check posthog/posthog-js then posthog/posthog", "posthog/posthog-js"),
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


class TestExtractLinkedRepo:
    @parameterized.expand(
        [
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
            ("userinfo_spoof", "see https://github.com@evil.tld/posthog/posthog", None),
            ("org_url_names_no_repo", "see https://github.com/posthog", None),
            ("unparseable_url_is_not_an_error", "see https://[::1/posthog/posthog", None),
            ("bare_token_is_not_a_link", "fix posthog/posthog-js now", None),
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
    def test_resolves_a_single_linked_repo(self, _name: str, text: str, expected: str | None):
        assert extract_linked_repo(text, REPOS) == expected


class TestExtractRepoFromScopes:
    @parameterized.expand(
        [
            (
                "later_scope_answers_when_earlier_names_nothing",
                ["can you look at this?", "https://github.com/posthog/posthog-js/actions/runs/2"],
                "posthog/posthog-js",
            ),
            (
                "typed_token_in_an_earlier_scope_beats_a_link_in_a_later_one",
                ["fix posthog/posthog", "https://github.com/posthog/posthog-js/actions/runs/2"],
                "posthog/posthog",
            ),
            (
                "typed_token_beats_a_link_in_the_same_scope",
                ["fix posthog/posthog-js, context https://github.com/posthog/posthog/pull/1"],
                "posthog/posthog-js",
            ),
            (
                "two_repos_in_one_scope_stay_ambiguous",
                [
                    "https://github.com/posthog/posthog/pull/1 broke https://github.com/posthog/posthog-js/actions/runs/2",
                    "https://github.com/posthog/posthog.com/pull/3",
                ],
                "posthog/posthog.com",
            ),
            (
                "two_repos_across_separate_scopes_resolve_to_the_first",
                [
                    "https://github.com/posthog/posthog/pull/1",
                    "https://github.com/posthog/posthog-js/actions/runs/2",
                ],
                "posthog/posthog",
            ),
            ("no_scope_names_a_repo", ["can you look at this?", "it broke again"], None),
            ("no_scopes_at_all", [], None),
        ]
    )
    def test_first_scope_to_name_a_repo_answers(self, _name: str, scopes: list[str], expected: str | None):
        assert extract_repo_from_scopes(scopes, REPOS) == expected
