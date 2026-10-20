from collections.abc import Iterator
from dataclasses import field
from threading import Event
from time import monotonic
from typing import cast

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from requests import Response

from posthog.dataclasses import frozen
from posthog.ownership.paths import UNOWNED_TEAM, resolve_path_owners
from posthog.ownership.repo_files import _MAX_FILE_BYTES, GitHubRepoFiles, OwnershipUnavailable, capped_text

_ROOT_OWNERS = """version: 1
owners: [team-root]
teams:
  team-ingestion:
    notifications: '#alerts-ingestion'
"""

_OWNERS = {
    "owners.yaml": _ROOT_OWNERS,
    "nodejs/src/owners.yaml": "version: 1\nowners: [team-ingestion]\n",
}


@frozen(frozen=False)
class _FakeRepoFiles:
    owners: dict[str, str] = field(default_factory=lambda: dict(_OWNERS))

    def read(self, path: str) -> str | None:
        return self.owners.get(path)

    def read_all(self, paths: list[str]) -> None:
        pass


class TestPathOwnership(SimpleTestCase):
    def test_places_each_path_exactly_and_returns_the_registry(self) -> None:
        # Exact resolution, not the suite-root search: 'src/...' is a real repo-relative path here
        # and must not be repositioned under nodejs/ the way a reported test path is.
        owned = resolve_path_owners(
            "PostHog/posthog",
            ["nodejs/src/cdp/worker.ts", "src/cdp/worker.ts"],
            files=_FakeRepoFiles(),
        )
        assert owned.resolved
        assert owned.team_by_path == {"nodejs/src/cdp/worker.ts": "team-ingestion", "src/cdp/worker.ts": "team-root"}
        assert owned.registry["team-ingestion"].notifications == "#alerts-ingestion"

    def test_an_unreadable_repository_owns_nothing_and_says_so(self) -> None:
        no_root = _FakeRepoFiles(owners={k: v for k, v in _OWNERS.items() if k != "owners.yaml"})
        owned = resolve_path_owners("PostHog/posthog", ["nodejs/src/cdp/worker.ts"], files=no_root)
        assert not owned.resolved
        assert owned.team_by_path == {"nodejs/src/cdp/worker.ts": UNOWNED_TEAM}
        assert owned.registry == {}


class TestGitHubRepoFiles(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    @parameterized.expand([(500,), (403,)])
    def test_an_unexpected_status_raises_rather_than_reading_as_absent(self, status: int) -> None:
        # Reading a failure as "no such file" reattributes everything under it to an ancestor.
        with patch(
            "posthog.ownership.repo_files.github_request",
            return_value=_response(status),
        ):
            with self.assertRaises(OwnershipUnavailable):
                GitHubRepoFiles("PostHog/posthog").read("owners.yaml")

    def test_a_missing_file_is_absent_and_fetched_once(self) -> None:
        with patch(
            "posthog.ownership.repo_files.github_request",
            return_value=_response(404),
        ) as request:
            files = GitHubRepoFiles("PostHog/posthog")
            assert files.read("nodejs/owners.yaml") is None
            assert files.read("nodejs/owners.yaml") is None
            assert GitHubRepoFiles("PostHog/posthog").read("nodejs/owners.yaml") is None
        assert request.call_count == 1

    def test_a_slow_repository_gives_up_instead_of_holding_the_worker(self) -> None:
        # A cold board asks for hundreds of files. Without a budget for the whole resolution, a
        # stalled raw host holds a web worker far past the per-request timeout.
        started, release, finished = Event(), Event(), Event()
        self.addCleanup(release.set)

        def stalls(_method: str, _url: str, **_kwargs: object) -> _response:
            started.set()
            release.wait(timeout=10)
            finished.set()
            return _response(404)

        files = GitHubRepoFiles("PostHog/posthog")

        def at_the_deadline_once_the_fetch_runs() -> float:
            assert started.wait(timeout=10)
            return files._deadline

        with (
            patch("posthog.ownership.repo_files.github_request", side_effect=stalls),
            patch(
                "posthog.ownership.repo_files.monotonic",
                side_effect=at_the_deadline_once_the_fetch_runs,
            ),
        ):
            with self.assertRaises(OwnershipUnavailable):
                files.read("owners.yaml")
        assert not finished.is_set()

    def test_a_body_that_arrives_after_the_deadline_is_refused(self) -> None:
        # The per-request timeout starts again on each chunk, so the byte limit alone lets one read
        # run for minutes. Nothing waits for the fetch after the deadline, so nothing else stops it.
        with self.assertRaises(OwnershipUnavailable):
            capped_text(
                cast(Response, _response(200, body=b"owners")),
                description="owners.yaml",
                limit=_MAX_FILE_BYTES,
                deadline=monotonic() - 1,
            )

    @parameterized.expand([("declared", True), ("streamed", False)])
    def test_an_oversized_file_is_refused(self, _name: str, declare_length: bool) -> None:
        # A connected repository controls these files, so an unbounded read would put its bytes in
        # a worker's memory and in Redis. Content-Length can lie, so the streamed read is the ceiling.
        oversized = b"x" * (_MAX_FILE_BYTES + 1)
        headers = {"Content-Length": str(len(oversized))} if declare_length else {}
        with patch(
            "posthog.ownership.repo_files.github_request",
            return_value=_response(200, body=oversized, headers=headers),
        ):
            with self.assertRaises(OwnershipUnavailable):
                GitHubRepoFiles("PostHog/posthog").read("owners.yaml")


class _response:
    encoding = "utf-8"

    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._body = body

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start : start + chunk_size]

    def __enter__(self) -> "_response":
        return self

    def __exit__(self, *args: object) -> None:
        pass
