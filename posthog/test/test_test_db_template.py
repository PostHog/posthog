import os
import re
import gzip
import uuid
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

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
        recorded = [("posthog", name) for name in migrations] + list(other_apps)
        rows = "".join(f"{index}\t{app}\t{name}\n" for index, (app, name) in enumerate(recorded, start=1))
        dump = tmp_path / "schema.sql.gz"
        dump.write_bytes(
            gzip.compress(
                (
                    "CREATE TABLE public.django_migrations (id serial PRIMARY KEY, app text, name text);\n"
                    f"COPY public.django_migrations (id, app, name) FROM stdin;\n{rows}\\.\n"
                ).encode()
            )
        )
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


@pytest.mark.parametrize(
    "start, ledger",
    [(None, None), ([APPLIED, FROM_NEWER_BRANCH], {APPLIED, FROM_NEWER_BRANCH})],
    ids=["missing", "newer-than-checkout"],
)
def test_prime_test_database_leaves_the_database_alone_without_a_template_from_the_checkout_history(
    scratch: Scratch, tmp_path: Path, start: list[str] | None, ledger: set[str] | None
) -> None:
    scratch.build_template(NOT_IN_HISTORY, [APPLIED, PENDING], tmp_path)
    if start is not None:
        scratch.seed(scratch.target, start)

    result = prime_test_database(scratch.server, scratch.target, scratch.store)

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
    (history / "products").mkdir(parents=True)
    (history / "products" / "db_routing.yaml").write_text(routing)
    git = ["git", "-C", str(history), "-c", "user.name=test", "-c", "user.email=test@example.com"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "routing"], check=True)
    sha = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
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


def test_postgres_server_connects_with_the_tls_settings_of_the_django_database() -> None:
    tls = {"sslmode": "require", "sslrootcert": "system"}
    server = PostgresServer.from_django({**settings.DATABASES["default"], "OPTIONS": tls})

    with pytest.raises(
        psycopg.OperationalError, match='weak sslmode "require" may not be used with sslrootcert=system'
    ):
        server.database_exists("postgres")
