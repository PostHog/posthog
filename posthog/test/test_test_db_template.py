import gzip
import uuid
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from django.conf import settings

from hogli_commands import db_template
from hogli_commands.db_template import Checkout, PostgresServer, PrimeOutcome, TemplateStore, prime_test_database
from psycopg.conninfo import conninfo_to_dict

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

    def build_template(self, sha: str, migrations: list[str], tmp_path: Path) -> None:
        rows = "".join(f"{index}\tposthog\t{name}\n" for index, name in enumerate(migrations, start=1))
        dump = tmp_path / "schema.sql.gz"
        dump.write_bytes(
            gzip.compress(
                (
                    "CREATE TABLE public.django_migrations (id serial PRIMARY KEY, app text, name text);\n"
                    f"COPY public.django_migrations (id, app, name) FROM stdin;\n{rows}\\.\n"
                ).encode()
            )
        )
        self.store.build(self.store.name_for(sha), dump)

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


def test_usable_template_tries_one_failed_download_per_retry_window(
    scratch: Scratch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[None] = []

    def unreachable_github() -> str:
        attempts.append(None)
        raise ConnectionError("github.com is unreachable")

    monkeypatch.setattr(db_template, "github_token", unreachable_github)
    workers = [
        TemplateStore(
            scratch.server, Checkout(REPO_ROOT), prefix=scratch.store.prefix, failure_marker=tmp_path / "failed"
        )
        for _ in range(3)
    ]

    for worker in workers:
        with pytest.raises((ConnectionError, db_template.TemplateUnavailable)):
            worker.usable_template()

    assert len(attempts) == 1


def test_postgres_server_keeps_the_tls_settings_of_the_django_database() -> None:
    server = PostgresServer.from_django(
        {
            "HOST": "db.example.com",
            "PASSWORD": "not-a-real-password",
            "OPTIONS": {"sslmode": "verify-full", "sslrootcert": "/certs/ca.pem", "connect_timeout": 3},
        }
    )

    assert conninfo_to_dict(server.conninfo("test_posthog")) == {
        "host": "db.example.com",
        "port": "5432",
        "user": "posthog",
        "dbname": "test_posthog",
        "sslmode": "verify-full",
        "sslrootcert": "/certs/ca.pem",
    }
