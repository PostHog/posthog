import io
import os
import re
import gzip
import json
import uuid
import zipfile
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from django.conf import settings

import psycopg
import requests
import responses
from hogli_commands import db_template
from hogli_commands.db_template import (
    Checkout,
    PostgresServer,
    PrimeOutcome,
    PrimeResult,
    TemplateStore,
    prime_test_database,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
APPLIED, PENDING = sorted(path.stem for path in (REPO_ROOT / "posthog" / "migrations").glob("0*.py"))[1:3]
FROM_NEWER_BRANCH = "9999_from_a_newer_branch"
NOT_IN_HISTORY = "0123456789ab"


def schema_dump(recorded: list[tuple[str, str]], *, preamble: str = "") -> bytes:
    rows = "".join(f"{index}\t{app}\t{name}\n" for index, (app, name) in enumerate(recorded, start=1))
    return gzip.compress(
        (
            preamble + "CREATE TABLE public.django_migrations (id serial PRIMARY KEY, app text, name text);\n"
            f"COPY public.django_migrations (id, app, name) FROM stdin;\n{rows}\\.\n"
        ).encode()
    )


def git_history(root: Path, commits: list[dict[str, str]]) -> list[str]:
    git = ["git", "-C", str(root), "-c", "user.name=test", "-c", "user.email=test@example.com"]
    root.mkdir(parents=True)
    subprocess.run([*git, "init", "-q"], check=True)
    shas = []
    for index, files in enumerate(commits):
        for path, content in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(content)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run(
            [*git, "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", f"c{index}"], check=True
        )
        shas.append(
            subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        )
    return shas


@dataclass(frozen=True, kw_only=True, slots=True)
class UploadedArtifact:
    id: int
    run_id: int
    head_sha: str
    name: str
    archive: bytes


@dataclass(frozen=True, kw_only=True, slots=True)
class GitHubActions:
    artifacts: list[UploadedArtifact] = field(default_factory=list)
    api: str = "https://api.github.com/repos/PostHog/posthog/actions"

    def upload(self, *, run_id: int, head_sha: str, name: str, files: dict[str, bytes]) -> None:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            for path, content in files.items():
                zipped.writestr(path, content)
        self.artifacts.append(
            UploadedArtifact(
                id=len(self.artifacts) + 1, run_id=run_id, head_sha=head_sha, name=name, archive=archive.getvalue()
            )
        )

    def _describe(self, artifact: UploadedArtifact) -> dict[str, object]:
        return {
            "id": artifact.id,
            "name": artifact.name,
            "expired": False,
            "size_in_bytes": len(artifact.archive),
            "archive_download_url": f"{self.api}/artifacts/{artifact.id}/zip",
            "created_at": f"2026-01-01T00:00:{artifact.id:02d}Z",
            "workflow_run": {
                "id": artifact.run_id,
                "head_sha": artifact.head_sha,
                "head_branch": "master",
                "head_repository_id": 1,
                "repository_id": 1,
            },
        }

    def _listing(self, matches: Callable[[UploadedArtifact], bool]) -> tuple[int, dict[str, str], str]:
        listed = [self._describe(artifact) for artifact in reversed(self.artifacts) if matches(artifact)]
        return 200, {"Content-Type": "application/json"}, json.dumps({"total_count": len(listed), "artifacts": listed})

    def _list_artifacts(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        names = parse_qs(urlsplit(request.url or "").query).get("name")
        return self._listing(lambda artifact: names is None or artifact.name in names)

    def _list_run_artifacts(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        run_id = int(urlsplit(request.url or "").path.split("/")[-2])
        return self._listing(lambda artifact: artifact.run_id == run_id)

    def _download(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], bytes]:
        artifact_id = int(urlsplit(request.url or "").path.split("/")[-2])
        found = [artifact.archive for artifact in self.artifacts if artifact.id == artifact_id]
        return (200, {}, found[0]) if found else (404, {}, b"")

    @contextmanager
    def serving(self) -> Iterator[None]:
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            prefix = re.escape(self.api)
            http.add_callback(responses.GET, re.compile(rf"{prefix}/artifacts(\?.*)?$"), self._list_artifacts)
            http.add_callback(
                responses.GET, re.compile(rf"{prefix}/runs/\d+/artifacts(\?.*)?$"), self._list_run_artifacts
            )
            http.add_callback(responses.GET, re.compile(rf"{prefix}/artifacts/\d+/zip$"), self._download)
            yield


@dataclass(frozen=True, kw_only=True, slots=True)
class Scratch:
    server: PostgresServer
    store: TemplateStore
    target: str
    head: str

    def seed(self, dbname: str, migrations: list[str] | None) -> None:
        self.server.create_database(dbname)
        if migrations is None:
            return
        with self.server.connect(dbname) as connection:
            connection.execute("CREATE TABLE django_migrations (id serial PRIMARY KEY, app text, name text)")
            for name in migrations:
                connection.execute("INSERT INTO django_migrations (app, name) VALUES ('posthog', %s)", (name,))

    def build_template(
        self,
        sha: str,
        migrations: list[str],
        tmp_path: Path,
        store: TemplateStore | None = None,
        other_apps: tuple[tuple[str, str], ...] = (),
    ) -> None:
        dump = tmp_path / "schema.sql.gz"
        dump.write_bytes(schema_dump([("posthog", name) for name in migrations] + list(other_apps)))
        store = store or self.store
        store.build(store.name_for(sha), dump, sha=sha)

    def ledger(self) -> set[str] | None:
        if not self.server.database_exists(self.target):
            return None
        return {migration.name for migration in self.server.recorded_migrations(self.target)}


@pytest.fixture
def scratch() -> Iterator[Scratch]:
    database = settings.DATABASES["default"]
    server = PostgresServer(
        host=database["HOST"] or "localhost",
        port=str(database["PORT"] or "5432"),
        user=database["USER"],
        password=database["PASSWORD"],
    )
    prefix = f"test_tpltest_{uuid.uuid4().hex[:8]}_"
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    yield Scratch(
        server=server,
        store=TemplateStore(server, Checkout(REPO_ROOT), allow_download=False, prefix=prefix + "tpl_"),
        target=prefix + "target",
        head=head.stdout.strip(),
    )
    for name in server.newest_databases_named(prefix):
        server.drop_database(name)


@pytest.mark.parametrize(
    "start, busy, outcome, ledger",
    [
        (None, False, PrimeOutcome.CLONED, {APPLIED, PENDING}),
        ([], False, PrimeOutcome.CLONED, {APPLIED, PENDING}),
        ([APPLIED, FROM_NEWER_BRANCH], False, PrimeOutcome.CLONED, {APPLIED, PENDING}),
        ([APPLIED], False, PrimeOutcome.KEPT, {APPLIED}),
        ([APPLIED, FROM_NEWER_BRANCH], True, PrimeOutcome.SKIPPED, {APPLIED, FROM_NEWER_BRANCH}),
    ],
    ids=["missing", "no-ledger", "newer-than-checkout", "behind-checkout", "newer-but-in-use"],
)
def test_prime_test_database_clones_the_template_unless_the_database_fits_the_checkout(
    scratch: Scratch, tmp_path: Path, start: list[str] | None, busy: bool, outcome: PrimeOutcome, ledger: set[str]
) -> None:
    scratch.build_template(scratch.head, [APPLIED, PENDING], tmp_path)
    if start is not None or busy:
        scratch.seed(scratch.target, start)

    if busy:
        with scratch.server.connect(scratch.target):
            result = prime_test_database(scratch.server, scratch.target, scratch.store)
    else:
        result = prime_test_database(scratch.server, scratch.target, scratch.store)

    assert (result.outcome, scratch.ledger()) == (outcome, ledger)


@pytest.mark.parametrize("template", ["not-in-history", "records-a-reverted-migration"])
@pytest.mark.parametrize(
    "start, ledger",
    [(None, None), ([APPLIED, FROM_NEWER_BRANCH], {APPLIED, FROM_NEWER_BRANCH})],
    ids=["missing", "newer-than-checkout"],
)
def test_prime_test_database_leaves_the_database_alone_without_a_template_that_fits_the_checkout(
    scratch: Scratch,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    template: str,
    start: list[str] | None,
    ledger: set[str] | None,
) -> None:
    github = GitHubActions()
    if template == "not-in-history":
        scratch.build_template(NOT_IN_HISTORY, [APPLIED, PENDING], tmp_path)
    else:
        reverted = [APPLIED, PENDING, FROM_NEWER_BRANCH]
        scratch.seed(scratch.store.name_for(scratch.head), reverted)
        dump = schema_dump([("posthog", name) for name in reverted], preamble=f"-- {os.urandom(16_000).hex()}\n")
        github.upload(run_id=7, head_sha=scratch.head, name="migrated-schema", files={"schema.sql.gz": dump})
        github.upload(run_id=7, head_sha=scratch.head, name=f"migrated-schema-mirrored-{scratch.head}", files={})
    if start is not None:
        scratch.seed(scratch.target, start)
    monkeypatch.setenv("GH_TOKEN", "gho_not_a_real_token")
    store = TemplateStore(
        scratch.server, Checkout(REPO_ROOT), prefix=scratch.store.prefix, failure_marker=tmp_path / "download-failed"
    )

    with github.serving():
        result = prime_test_database(scratch.server, scratch.target, store)

    assert (result.outcome, scratch.ledger()) == (PrimeOutcome.SKIPPED, ledger)


@pytest.mark.parametrize(
    "routing, other_apps, ledger",
    [
        ("routes:\n  - app_label: posthog\n", (), set()),
        (
            "routes: []\n",
            (("stamphog", "0002_a_routed_app_migration"),),
            {APPLIED, PENDING, "0002_a_routed_app_migration"},
        ),
    ],
    ids=["routed-away-at-the-template-commit", "routed-away-only-in-the-checkout"],
)
def test_prime_test_database_clears_only_the_apps_the_template_commit_routed_to_another_database(
    scratch: Scratch, tmp_path: Path, routing: str, other_apps: tuple[tuple[str, str], ...], ledger: set[str]
) -> None:
    history = tmp_path / "history"
    [sha] = git_history(history, [{"products/db_routing.yaml": routing}])
    store = TemplateStore(scratch.server, Checkout(history), allow_download=False, prefix=scratch.store.prefix)
    scratch.build_template(sha, [APPLIED, PENDING], tmp_path, store, other_apps)

    result = prime_test_database(scratch.server, scratch.target, store)

    assert (result.outcome, scratch.ledger()) == (PrimeOutcome.CLONED, ledger)


@pytest.mark.parametrize(
    "mode, naming",
    [("auto", "test-name"), ("auto", "default-name"), ("off", "test-name")],
)
def test_prime_django_test_database_primes_the_test_database_of_the_django_settings(
    scratch: Scratch, monkeypatch: pytest.MonkeyPatch, mode: str, naming: str
) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv(db_template.MODE_ENV, mode)
    scratch.seed(scratch.target, [APPLIED])
    database = dict(settings.DATABASES["default"])
    if naming == "test-name":
        database |= {"NAME": "posthog", "TEST": {"NAME": scratch.target}}
    else:
        database |= {"NAME": scratch.target.removeprefix("test_"), "TEST": {}}

    result = db_template.prime_django_test_database(database)

    kept = PrimeResult(outcome=PrimeOutcome.KEPT, detail=f"{scratch.target} fits this checkout")
    assert result == (None if mode == "off" else kept)


@pytest.mark.parametrize(
    "marker, outcome, ledger",
    [("dumped", PrimeOutcome.CLONED, set()), ("not-in-history", PrimeOutcome.SKIPPED, None)],
)
def test_prime_test_database_routes_a_downloaded_template_by_the_commit_the_mirror_dumped(
    scratch: Scratch,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker: str,
    outcome: PrimeOutcome,
    ledger: set[str] | None,
) -> None:
    history = tmp_path / "history"
    dumped, mirrored_at = git_history(
        history,
        [
            {"products/db_routing.yaml": "routes:\n  - app_label: posthog\n"},
            {"products/db_routing.yaml": "routes: []\n"},
        ],
    )
    monkeypatch.setenv("GH_TOKEN", "gho_not_a_real_token")
    store = TemplateStore(
        scratch.server, Checkout(history), prefix=scratch.store.prefix, failure_marker=tmp_path / "download-failed"
    )
    recorded = [("posthog", APPLIED), ("posthog", PENDING)]
    github = GitHubActions()
    github.upload(
        run_id=7,
        head_sha=mirrored_at,
        name="migrated-schema",
        files={"schema.sql.gz": schema_dump(recorded, preamble=f"-- {os.urandom(16_000).hex()}\n")},
    )
    github.upload(
        run_id=7,
        head_sha=mirrored_at,
        name=f"migrated-schema-mirrored-{dumped if marker == 'dumped' else 'f' * 40}",
        files={},
    )

    with github.serving():
        result = prime_test_database(scratch.server, scratch.target, store)

    assert (result.outcome, scratch.ledger()) == (outcome, ledger)


def test_usable_template_retries_a_failed_download_only_after_the_retry_window(
    scratch: Scratch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "gho_not_a_real_token")
    marker = tmp_path / "download-failed"

    def worker() -> TemplateStore:
        return TemplateStore(scratch.server, Checkout(REPO_ROOT), prefix=scratch.store.prefix, failure_marker=marker)

    with responses.RequestsMock(assert_all_requests_are_fired=False) as github:
        github.get(re.compile(r"https://api\.github\.com/.*"), status=401)
        for _ in range(3):
            with pytest.raises((requests.HTTPError, db_template.TemplateUnavailable)):
                worker().usable_template()
        requests_within_window = len(github.calls)

        os.utime(marker, (0, 0))
        with pytest.raises(requests.HTTPError):
            worker().usable_template()
        requests_in_total = len(github.calls)

    assert (requests_within_window, requests_in_total) == (1, 2)


@pytest.mark.parametrize(
    "options, refusal",
    [
        (
            {"sslmode": "require", "sslrootcert": "system"},
            'weak sslmode "require" may not be used with sslrootcert=system',
        ),
        ({"sslmode": "disable", "channel_binding": "require"}, "channel binding required, but SSL not in use"),
    ],
    ids=["tls", "channel-binding"],
)
def test_postgres_server_connects_with_the_security_settings_of_the_django_database(
    options: dict[str, str], refusal: str
) -> None:
    server = PostgresServer.from_django({**settings.DATABASES["default"], "OPTIONS": options})

    with pytest.raises(psycopg.OperationalError, match=refusal):
        server.database_exists("postgres")
