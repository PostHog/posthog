from collections.abc import Callable
from threading import Event
from time import monotonic
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.ownership.github_files import _CHUNK_FILES, AuthenticatedRepoFiles, GitHubFilesFetcher, fetcher_for_team
from posthog.ownership.repo_files import GitHubRepoFiles, OwnershipUnavailable

_REPOSITORY = "PostHog/posthog"
_SHA = "a" * 40
_ROOT_OWNERS = "version: 1\nowners: [team-root]\n"


class _Response:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("no body")
        return self._body


class _FakeGitHub:
    """Answers the two queries this module sends, and counts what it was asked."""

    def __init__(self, blobs: dict[str, str], *, sha: str = _SHA) -> None:
        self.blobs = blobs
        self.sha = sha
        self.file_calls = 0
        self.head_calls = 0

    def __call__(self, _method: str, _url: str, **kwargs: Any) -> _Response:
        payload = kwargs["json"]
        query, variables = payload["query"], payload["variables"]
        if "defaultBranchRef" in query:
            self.head_calls += 1
            return _Response(200, {"data": {"repository": {"defaultBranchRef": {"target": {"oid": self.sha}}}}})
        self.file_calls += 1
        field: dict[str, Any] = {}
        for name, expression in variables.items():
            if name in ("owner", "name"):
                continue
            path = expression.split(":", 1)[1]
            body = self.blobs.get(path)
            if body is None:
                field[f"f{name[1:]}"] = None
            else:
                field[f"f{name[1:]}"] = {"text": body} if "text" in query else {"__typename": "Blob"}
        return _Response(200, {"data": {"repository": field}})


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

    def test_existence_is_answered_without_a_body(self) -> None:
        # Most probed paths are candidates a batch only wants to rule out, and one of them can be a
        # whole source file.
        github = _FakeGitHub({"nodejs/owners.yaml": _ROOT_OWNERS})
        with patch("posthog.ownership.github_files.github_request", side_effect=github):
            exists = _fetcher().files_exist(_REPOSITORY, _SHA, ["nodejs/owners.yaml", "gone.yaml"], monotonic() + 30)
        assert exists == {"nodejs/owners.yaml": True, "gone.yaml": False}

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
            ("unparseable", lambda: _Response(200, None)),
            ("not_an_object", lambda: _Response(200, [{"message": "NOT_FOUND"}])),
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

    def test_a_partially_failed_answer_caches_no_absence(self) -> None:
        # An errored alias comes back null, exactly like a file the commit does not hold. Caching
        # that as an absence would hold for days and move every path under it to an ancestor.
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

    @parameterized.expand([("present", _ROOT_OWNERS), ("absent", None)])
    def test_a_commit_is_read_once_and_a_new_commit_is_read_again(self, _name: str, body: str | None) -> None:
        # The cache is keyed by commit, so a merge has to be visible once the head lookup expires,
        # and an absent file must not be refetched on every batch until then.
        github = _FakeGitHub({"owners.yaml": body} if body is not None else {})
        with (
            patch("posthog.ownership.github_files._HEAD_CACHE_TTL_SECONDS", 0),
            patch("posthog.ownership.github_files.github_request", side_effect=github),
        ):
            assert self._files().read("owners.yaml") == body
            assert self._files().read("owners.yaml") == body
            assert github.file_calls == 1
            github.sha = "b" * 40
            assert self._files().read("owners.yaml") == body
            assert github.file_calls == 2


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
