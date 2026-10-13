import json
from collections.abc import Callable, Iterator
from threading import Event
from time import monotonic
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.ownership.github_files import (
    _CACHE_PREFIX,
    _CHUNK_FILES,
    _MAX_RESPONSE_BYTES,
    AuthenticatedRepoFiles,
    GitHubFilesFetcher,
    fetcher_for_team,
)
from posthog.ownership.repo_files import GitHubRepoFiles, OwnershipUnavailable

_REPOSITORY = "PostHog/posthog"
_SHA = "a" * 40
_NEW_SHA = "b" * 40
_ROOT_OWNERS = "version: 1\nowners: [team-root]\n"


class _Response:
    def __init__(self, status: int, body: Any, *, raw: bytes | None = None) -> None:
        self.status_code = status
        self.headers: dict[str, str] = {}
        self.encoding = "utf-8"
        self._raw = raw if raw is not None else json.dumps(body).encode()

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        for start in range(0, len(self._raw), chunk_size):
            yield self._raw[start : start + chunk_size]

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


class _FakeGitHub:
    """Answers the two queries this module sends, and counts what it was asked."""

    def __init__(self, blobs: dict[str, str], *, sha: str | None = _SHA, trees: frozenset[str] = frozenset()) -> None:
        self.blobs = blobs
        self.trees = trees
        self.sha = sha
        self.file_calls = 0
        self.head_calls = 0
        self.file_shas: list[str] = []
        self.compare_calls = 0
        self.compare: Callable[[str, str], _Response] = lambda base, _head: _compared(base, [])

    def __call__(self, _method: str, url: str, **kwargs: Any) -> _Response:
        if "/compare/" in url:
            self.compare_calls += 1
            base, head = url.rsplit("/", 1)[1].split("...")
            return self.compare(base, head)
        payload = kwargs["json"]
        query, variables = payload["query"], payload["variables"]
        if "defaultBranchRef" in query:
            self.head_calls += 1
            # A repository with no commits has no default branch, and GitHub says so with a null.
            ref = {"target": {"oid": self.sha}} if self.sha is not None else None
            return _Response(200, {"data": {"repository": {"defaultBranchRef": ref}}})
        self.file_calls += 1
        field: dict[str, Any] = {}
        for name, expression in variables.items():
            if name in ("owner", "name"):
                continue
            sha, path = expression.split(":", 1)
            self.file_shas.append(sha)
            body = self.blobs.get(path)
            if path in self.trees:
                field[f"f{name[1:]}"] = {} if "text" in query else {"__typename": "Tree"}
            elif body is None:
                field[f"f{name[1:]}"] = None
            else:
                field[f"f{name[1:]}"] = {"text": body} if "text" in query else {"__typename": "Blob"}
        return _Response(200, {"data": {"repository": field}})


def _compared(
    base: str, files: list[dict[str, str]], *, status: str = "ahead", merge_base: str | None = None
) -> _Response:
    return _Response(200, {"status": status, "merge_base_commit": {"sha": merge_base or base}, "files": files})


class _ScriptedGitHub:
    """Answers a files query with the scripted status codes in order, recording each token used."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses = statuses
        self.tokens: list[str] = []

    def __call__(self, _method: str, _url: str, **kwargs: Any) -> _Response:
        self.tokens.append(kwargs["headers"]["Authorization"])
        status = self._statuses[len(self.tokens) - 1]
        if status != 200:
            return _Response(status, {"message": "Bad credentials"})
        return _Response(200, {"data": {"repository": {"f0": {"text": _ROOT_OWNERS}}}})


def _fetcher() -> GitHubFilesFetcher:
    return GitHubFilesFetcher.from_token("t0ken", installation_id="42", priority=Priority.BATCH)


class TestGitHubFilesFetcher(SimpleTestCase):
    def test_a_batch_is_split_into_chunks_and_a_missing_file_comes_back_absent(self) -> None:
        # GitHub answers a few hundred aliased blobs with a 502, so one batch has to be several
        # requests, and every path has to survive the split.
        present = [f"d{index}/owners.yaml" for index in range(_CHUNK_FILES)]
        github = _FakeGitHub(dict.fromkeys(present, _ROOT_OWNERS))
        with patch("posthog.ownership.github_files.github_request", side_effect=github):
            read = _fetcher().read_files(_REPOSITORY, _SHA, [*present, "gone/owners.yaml"], monotonic() + 30)
        assert github.file_calls == 2
        assert read[present[0]] == _ROOT_OWNERS
        assert read["gone/owners.yaml"] != _ROOT_OWNERS

    def test_a_repository_with_no_commits_names_no_head_instead_of_failing(self) -> None:
        # An empty repository answers with a null defaultBranchRef and no error. Failing it would
        # take down every other repository the same run reads.
        github = _FakeGitHub({}, sha=None)
        with patch("posthog.ownership.github_files.github_request", side_effect=github):
            assert _fetcher().head_commit_sha(_REPOSITORY) is None

    def test_existence_is_answered_without_a_body(self) -> None:
        # Most probed paths are candidates a batch only wants to rule out, and one of them can be a
        # whole source file.
        github = _FakeGitHub({"nodejs/owners.yaml": _ROOT_OWNERS}, trees=frozenset({"nodejs"}))
        with patch("posthog.ownership.github_files.github_request", side_effect=github):
            exists = _fetcher().files_exist(
                _REPOSITORY, _SHA, ["nodejs/owners.yaml", "gone.yaml", "nodejs"], monotonic() + 30
            )
        assert exists == {"nodejs/owners.yaml": True, "gone.yaml": False, "nodejs": False}

    @parameterized.expand(
        [
            ("server_error", lambda: _Response(502, None)),
            ("graphql_errors", lambda: _Response(200, {"data": None, "errors": [{"message": "NOT_FOUND"}]})),
            ("no_repository", lambda: _Response(200, {"data": {"repository": None}})),
            # A partial answer: the repository object is there, and only the failed aliases are null.
            (
                "partial_errors",
                lambda: _Response(200, {"data": {"repository": {"f0": None}}, "errors": [{"message": "TIMEOUT"}]}),
            ),
            ("unparseable", lambda: _Response(200, None, raw=b"<html>gateway</html>")),
            ("not_an_object", lambda: _Response(200, [{"message": "NOT_FOUND"}])),
            ("missing_alias", lambda: _Response(200, {"data": {"repository": {}}})),
            # GitHub cuts a large blob's text short and still answers 200, so the prefix would parse
            # as a complete file and cache a wrong answer for the whole TTL.
            (
                "truncated_blob",
                lambda: _Response(200, {"data": {"repository": {"f0": {"text": "own", "isTruncated": True}}}}),
            ),
            # The per-file limit alone lets one chunk of a hundred near-limit blobs materialize a
            # hundred megabytes, sixteen chunks at a time.
            ("oversized_answer", lambda: _Response(200, None, raw=b"x" * (_MAX_RESPONSE_BYTES + 1))),
        ]
    )
    def test_an_unreadable_answer_raises_rather_than_reading_as_absent(
        self, _name: str, answer: Callable[[], _Response]
    ) -> None:
        # A repository the credential cannot see answers the same way as one that declares nothing,
        # and reading that as "no owners" attributes the whole batch to nobody.
        with patch("posthog.ownership.github_files.github_request", side_effect=lambda *a, **kw: answer()):
            with self.assertRaises(OwnershipUnavailable):
                _fetcher().read_files(_REPOSITORY, _SHA, ["owners.yaml"], monotonic() + 30)

    @parameterized.expand(
        [
            # A credential that can be minted again retries once, so a token revoked or rotated under
            # the batch recovers instead of failing every read that follows it.
            ("mintable_recovers", True, [401, 200], 2, 1, False),
            ("mintable_gives_up_on_the_second_401", True, [401, 401], 2, 1, True),
            # A personal access token cannot be minted again, so a retry would only spend one more call.
            ("static_fails_closed", False, [401], 1, 0, True),
        ]
    )
    def test_a_401_asks_for_a_fresh_credential_once(
        self, _name: str, mintable: bool, statuses: list[int], calls: int, refreshes: int, fails: bool
    ) -> None:
        refreshed: list[str] = []

        def refresh() -> str:
            refreshed.append("fresh")
            return "fresh"

        github = _ScriptedGitHub(statuses)
        fetcher = GitHubFilesFetcher.from_token(
            "t0ken", installation_id="42", refresh=refresh if mintable else None, priority=Priority.BATCH
        )
        with patch("posthog.ownership.github_files.github_request", side_effect=github):
            if fails:
                with self.assertRaises(OwnershipUnavailable):
                    fetcher.read_files(_REPOSITORY, _SHA, ["owners.yaml"], monotonic() + 30)
            else:
                read = fetcher.read_files(_REPOSITORY, _SHA, ["owners.yaml"], monotonic() + 30)
                assert read == {"owners.yaml": _ROOT_OWNERS}
        assert len(github.tokens) == calls
        assert len(refreshed) == refreshes
        if mintable:
            assert github.tokens[-1] == "Bearer fresh"

    def test_an_installation_mints_the_replacement_token(self) -> None:
        # get_access_token keeps the stored token until it nears expiry, so it can hand back the very
        # token the 401 refused. Only a refresh mints a new one.
        integration = MagicMock(github_installation_id="42")
        integration.get_access_token.side_effect = ["stale", "fresh"]
        github = _ScriptedGitHub([401, 200])
        with patch("posthog.ownership.github_files.github_request", side_effect=github):
            GitHubFilesFetcher.from_integration(integration, priority=Priority.BATCH).read_files(
                _REPOSITORY, _SHA, ["owners.yaml"], monotonic() + 30
            )
        integration.refresh_access_token.assert_called_once()
        assert github.tokens == ["Bearer stale", "Bearer fresh"]

    def test_a_slow_repository_gives_up_instead_of_holding_the_worker(self) -> None:
        # A cold board asks for hundreds of files. Without a budget for the whole batch, a stalled
        # API holds a web worker far past the per-request timeout.
        release = Event()
        self.addCleanup(release.set)

        def stalls(*_args: Any, **_kwargs: Any) -> _Response:
            release.wait(timeout=10)
            return _Response(200, {"data": {"repository": {}}})

        with patch("posthog.ownership.github_files.github_request", side_effect=stalls):
            with self.assertRaises(OwnershipUnavailable):
                _fetcher().read_files(_REPOSITORY, _SHA, ["owners.yaml"], monotonic() - 1)


class TestAuthenticatedRepoFiles(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def _files(self) -> AuthenticatedRepoFiles:
        return AuthenticatedRepoFiles(_REPOSITORY, _fetcher())

    def test_a_burst_asks_github_for_the_head_commit_once(self) -> None:
        github = _FakeGitHub({"owners.yaml": _ROOT_OWNERS})
        with patch("posthog.ownership.github_files.github_request", side_effect=github):
            assert self._files().read("owners.yaml") == _ROOT_OWNERS
            assert self._files().read("owners.yaml") == _ROOT_OWNERS
        assert github.head_calls == 1

    def test_an_unreachable_cache_reads_from_github_instead_of_failing(self) -> None:
        github = _FakeGitHub({"owners.yaml": _ROOT_OWNERS})
        down = ConnectionError("redis is down")
        with (
            patch.object(cache, "get", side_effect=down),
            patch.object(cache, "set", side_effect=down),
            patch.object(cache, "get_many", side_effect=down),
            patch.object(cache, "set_many", side_effect=down),
            patch("posthog.ownership.github_files.github_request", side_effect=github),
        ):
            assert self._files().read("owners.yaml") == _ROOT_OWNERS

    def test_a_partially_failed_answer_caches_no_absence(self) -> None:
        # An errored alias comes back null, exactly like a file the commit does not hold. Caching
        # that as an absence would hold for the whole TTL and move every path under it to an ancestor.
        working = _FakeGitHub({"owners.yaml": _ROOT_OWNERS})

        def partial(method: str, url: str, **kwargs: Any) -> _Response:
            response = working(method, url, **kwargs)
            if "defaultBranchRef" in kwargs["json"]["query"]:
                return response
            return _Response(200, {"data": {"repository": {"f0": None}}, "errors": [{"message": "TIMEOUT"}]})

        with patch("posthog.ownership.github_files.github_request", side_effect=partial):
            with self.assertRaises(OwnershipUnavailable):
                self._files().read("owners.yaml")
        with patch("posthog.ownership.github_files.github_request", side_effect=working):
            assert self._files().read("owners.yaml") == _ROOT_OWNERS

    def test_an_empty_repository_reads_as_absent_and_caches_no_absence(self) -> None:
        # Every file of a repository with no commits is absent, and there is no commit to key that
        # absence by, so caching it would hold for the whole TTL and outlive the first push.
        github = _FakeGitHub({}, sha=None)
        with patch("posthog.ownership.github_files.github_request", side_effect=github):
            files = self._files()
            assert files.read("owners.yaml") is None
            assert files.exists_all(["owners.yaml"]) == {"owners.yaml": False}
        assert github.file_calls == 0

        github.sha, github.blobs = _SHA, {"owners.yaml": _ROOT_OWNERS}
        with patch("posthog.ownership.github_files.github_request", side_effect=github):
            assert self._files().read("owners.yaml") == _ROOT_OWNERS

    @parameterized.expand([("cached_head", False, _SHA), ("fresh_head", True, _NEW_SHA)])
    def test_a_fresh_head_run_reads_at_the_head_of_this_run(
        self, _name: str, fresh_head: bool, expected_sha: str
    ) -> None:
        # A caller that derives a decision it never stores cannot correct a head another caller
        # cached two minutes ago, so it has to be able to skip that entry. The entry is still
        # written, because every other caller is happy with it.
        github = _FakeGitHub({"owners.yaml": _ROOT_OWNERS}, sha=_NEW_SHA)
        key = f"{_CACHE_PREFIX}:head:{_fetcher().audience}:{_REPOSITORY}"
        cache.set(key, _SHA, 120)
        with patch("posthog.ownership.github_files.github_request", side_effect=github):
            files = AuthenticatedRepoFiles(_REPOSITORY, _fetcher(), fresh_head=fresh_head)
            assert files.read("owners.yaml") == _ROOT_OWNERS
        assert github.file_shas == [expected_sha]
        assert cache.get(key) == expected_sha

    @parameterized.expand(
        [
            ("unrelated_merge", lambda base, _head: _compared(base, [{"filename": "src/app.py"}]), 1, False),
            ("unrelated_merge_absent_file", lambda base, _head: _compared(base, []), 1, False, None),
            ("file_edited", lambda base, _head: _compared(base, [{"filename": "owners.yaml"}]), 2, True),
            (
                "file_renamed_away",
                lambda base, _head: _compared(base, [{"filename": "team.yaml", "previous_filename": "owners.yaml"}]),
                2,
                True,
            ),
            # A force-push or a rewind: the old head is not an ancestor, so nothing is proven unchanged.
            ("diverged", lambda base, _head: _compared(base, [], status="diverged"), 2, True),
            ("merge_base_elsewhere", lambda base, _head: _compared(base, [], merge_base="c" * 40), 2, True),
            (
                "file_list_cut_short",
                lambda base, _head: _compared(base, [{"filename": f"src/{index}.py"} for index in range(300)]),
                2,
                True,
            ),
            (
                "compare_too_large",
                lambda _base, _head: _Response(200, None, raw=b"x" * (_MAX_RESPONSE_BYTES + 1)),
                2,
                True,
            ),
            # A transient failure can succeed on the next batch, so it is asked again.
            ("compare_failed", lambda _base, _head: _Response(502, None), 2, True, _ROOT_OWNERS, 2),
        ]
    )
    def test_a_new_commit_reuses_only_what_the_compare_proves_unchanged(
        self,
        _name: str,
        compare: Callable[[str, str], _Response],
        file_calls: int,
        sees_edit: bool,
        body: str | None = _ROOT_OWNERS,
        compare_calls: int = 1,
    ) -> None:
        github = _FakeGitHub({"owners.yaml": body} if body is not None else {})
        github.compare = compare
        edited = "version: 1\nowners: [team-new]\n"
        with (
            patch("posthog.ownership.github_files._HEAD_CACHE_TTL_SECONDS", 0),
            patch("posthog.ownership.github_files.github_request", side_effect=github),
        ):
            assert self._files().read("owners.yaml") == body
            assert self._files().read("owners.yaml") == body
            assert github.file_calls == 1
            github.sha = _NEW_SHA
            if sees_edit:
                github.blobs = {"owners.yaml": edited}
            assert self._files().read("owners.yaml") == (edited if sees_edit else body)
            assert self._files().read("owners.yaml") == (edited if sees_edit else body)
            assert github.file_calls == file_calls
            # Another batch at the same head misses on a new path, and takes the compare answer from the cache.
            assert self._files().read("rust/owners.yaml") is None
        assert github.compare_calls == compare_calls


class TestFetcherForTeam(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    @parameterized.expand([("with_installation", True), ("without_installation", False)])
    def test_a_team_reads_authenticated_only_where_its_installation_covers_the_repository(
        self, _name: str, covered: bool
    ) -> None:
        # The lookup probes GitHub once per integration the team has, and a page load asks for the
        # reader on every request, so the decision has to survive the next one.
        integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="42",
            config={"account": {"name": "PostHog"}},
            sensitive_config={"access_token": "t0ken"},
        )
        with patch(
            "posthog.ownership.github_files.GitHubIntegration.first_for_team_repository",
            return_value=GitHubIntegration(integration) if covered else None,
        ) as probe:
            first = fetcher_for_team(self.team.pk, _REPOSITORY, priority=Priority.NORMAL)
            second = fetcher_for_team(self.team.pk, _REPOSITORY, priority=Priority.NORMAL)
        assert probe.call_count == 1
        expected = AuthenticatedRepoFiles if covered else GitHubRepoFiles
        assert isinstance(first, expected)
        assert isinstance(second, expected)

    @parameterized.expand(
        [
            ("our_budget", GitHubEgressBudgetExhausted("shed")),
            ("githubs_limit", GitHubRateLimitError("429")),
        ]
    )
    def test_a_spent_budget_degrades_to_the_anonymous_reader_without_a_cached_decision(
        self, _name: str, error: Exception
    ) -> None:
        # Callers evaluate this before their own unavailable-ownership handler runs, so a raise here
        # turns optional enrichment into a 500. The decision must not be cached either, or the
        # anonymous reader would outlive the exhausted budget by the cache's whole window.
        with patch(
            "posthog.ownership.github_files.GitHubIntegration.first_for_team_repository", side_effect=error
        ) as spent:
            assert isinstance(fetcher_for_team(self.team.pk, _REPOSITORY, priority=Priority.NORMAL), GitHubRepoFiles)
        assert spent.call_count == 1
        assert cache.get(f"{_CACHE_PREFIX}:integration:{self.team.pk}:{_REPOSITORY.casefold()}") is None
