import os
import sys
import subprocess
from pathlib import Path

import pytest

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
            # Markdown puts the URL inside `](...)`, so edge-punctuation stripping alone never sees it.
            (
                "markdown_link_label",
                "broke in [PR 1](https://github.com/posthog/posthog-js/pull/1)",
                "posthog/posthog-js",
            ),
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


BAKED_IN_SHA = "0123456789abcdef0123456789abcdef01234567"
INJECTED_SHA = "fedcba9876543210fedcba9876543210fedcba98"
REPO_ROOT = Path(__file__).resolve().parents[2]
PRINT_COMMITS = "from posthog.git import get_git_commit_full as f, get_git_commit_short as s; print(f(), s())"
FROM_GIT = "from git"


def hermetic_env(workdir: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("GIT_", "POSTHOG_GIT_COMMIT"))}
    return env | {
        "GIT_CEILING_DIRECTORIES": str(workdir.parent),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def git(workdir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=workdir, env=hermetic_env(workdir), capture_output=True, text=True, check=True
    ).stdout.strip()


def make_checkout(workdir: Path, source: str) -> tuple[str, str]:
    if source == "commit.txt":
        (workdir / "commit.txt").write_text(f"{BAKED_IN_SHA}\n")
    if source == "git":
        git(workdir, "init", "--quiet")
        git(
            workdir,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "head",
        )
        return git(workdir, "rev-parse", "HEAD"), git(workdir, "rev-parse", "--short", "HEAD")
    return "None", "None"


def commits_seen_by_a_process_in(workdir: Path, injected: str | None) -> tuple[str, str]:
    env = hermetic_env(workdir) | {"PYTHONPATH": str(REPO_ROOT)}
    if injected is not None:
        env["POSTHOG_GIT_COMMIT"] = injected
    output = subprocess.run(
        [sys.executable, "-c", PRINT_COMMITS], cwd=workdir, env=env, capture_output=True, text=True, check=True
    ).stdout
    full, short = output.split()
    return full, short


class TestGitCommit:
    @pytest.mark.parametrize(
        "source, injected, expected",
        [
            pytest.param("commit.txt", None, (BAKED_IN_SHA, BAKED_IN_SHA[:10]), id="baked_in"),
            pytest.param("commit.txt", INJECTED_SHA, (BAKED_IN_SHA, BAKED_IN_SHA[:10]), id="baked_in_beats_injected"),
            pytest.param("git", INJECTED_SHA, (INJECTED_SHA, INJECTED_SHA[:10]), id="injected_beats_git"),
            pytest.param("git", f"  {INJECTED_SHA}\n", (INJECTED_SHA, INJECTED_SHA[:10]), id="injected_is_stripped"),
            pytest.param("git", " \n ", FROM_GIT, id="blank_injected_falls_back_to_git"),
            pytest.param("git", None, FROM_GIT, id="unset_falls_back_to_git"),
            pytest.param("git", INJECTED_SHA[:10], FROM_GIT, id="abbreviated_injected_falls_back_to_git"),
            pytest.param(
                "git", f"{INJECTED_SHA[:5]}\n{INJECTED_SHA[6:]}", FROM_GIT, id="multiline_injected_falls_back_to_git"
            ),
            pytest.param("git", INJECTED_SHA.upper(), FROM_GIT, id="uppercase_injected_falls_back_to_git"),
            pytest.param("git", "g" * 40, FROM_GIT, id="non_hex_injected_falls_back_to_git"),
            pytest.param("nothing", INJECTED_SHA, (INJECTED_SHA, INJECTED_SHA[:10]), id="injected_without_git"),
            pytest.param("nothing", None, ("None", "None"), id="unknown"),
        ],
    )
    def test_resolves_the_running_commit(
        self, tmp_path: Path, source: str, injected: str | None, expected: tuple[str, str] | str
    ):
        from_git = make_checkout(tmp_path, source)
        assert commits_seen_by_a_process_in(tmp_path, injected) == (from_git if expected == FROM_GIT else expected)
