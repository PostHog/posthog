import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import patch

import responses
from infi.clickhouse_orm import Database
from requests import PreparedRequest

from posthog.clickhouse.client import connection
from posthog.clickhouse.client.connection import ClickHouseCredentials, ClickHouseUser
from posthog.management.commands.migrate_clickhouse import Command

CLICKHOUSE_URL = "http://clickhouse.example.com:8123/"
APPLY_OPTIONS = {"upto": 99_999, "fake": False, "check": False, "plan": False, "print_sql": False}
SERVER_ANSWERS = {
    "SELECT count() FROM system.databases": "1",
    "SELECT version()": "25.8.1.1",
    "SELECT timezone()": "UTC",
    "SELECT DISTINCT module_name": "module_name\nString\n",
}


def answer_server_query(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
    body = request.body.decode() if isinstance(request.body, bytes) else str(request.body)
    return 200, {}, next((text for query, text in SERVER_ANSWERS.items() if body.startswith(query)), "")


def basic_auth(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@pytest.mark.parametrize(
    "migrations_user_registered, first_request_auth, request_after_rotation_auth",
    [
        pytest.param(
            True,
            basic_auth("migrations", "token-1"),
            basic_auth("migrations", "token-2"),
            id="migrations_user_reads_its_token_per_request",
        ),
        pytest.param(
            False,
            basic_auth("default", "default-static"),
            basic_auth("default", "default-static"),
            id="unset_migrations_user_falls_back_to_default",
        ),
    ],
)
def test_migrate_authenticates_each_request_with_the_current_password(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    migrations_user_registered: bool,
    first_request_auth: str,
    request_after_rotation_auth: str,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("token-1")
    users = {ClickHouseUser.DEFAULT: ClickHouseCredentials(user="default", password="default-static")}
    if migrations_user_registered:
        users[ClickHouseUser.MIGRATIONS] = ClickHouseCredentials(
            user="migrations", password="", password_file=str(token_file)
        )
    monkeypatch.setattr(connection, "__user_dict", users)
    sent_auth: list[str] = []

    def answer(request: PreparedRequest) -> tuple[int, dict[str, str], str]:
        sent_auth.append(str(request.headers["Authorization"]))
        return answer_server_query(request)

    def apply_past_a_token_rotation(database: Database, *args: object, **kwargs: object) -> None:
        token_file.write_text("token-2")
        database._send("SELECT 1")

    with (
        responses.RequestsMock() as server,
        patch.object(Database, "migrate", autospec=True, side_effect=apply_past_a_token_rotation),
        patch("posthog.management.commands.migrate_clickhouse.default_client"),
    ):
        server.add_callback(responses.POST, CLICKHOUSE_URL, callback=answer)
        Command().migrate(CLICKHOUSE_URL, APPLY_OPTIONS)

    assert sent_auth[0] == first_request_auth
    assert sent_auth[-1] == request_after_rotation_auth


@pytest.mark.parametrize(
    "applied, upto, newly_applied",
    [
        pytest.param({"0001_a"}, 2, ["0002_b"], id="stops_at_upto"),
        pytest.param({"0001_a", "0002_b"}, 2, [], id="skips_a_pending_migration_after_upto"),
        pytest.param({"0002_b"}, 2, ["0001_a"], id="stops_at_the_last_pending_migration_below_upto"),
        pytest.param({"0001_a"}, 99_999, ["0002_b", "0003_c"], id="applies_every_pending_migration_by_default"),
    ],
)
def test_migrate_never_applies_a_migration_after_upto(applied: set[str], upto: int, newly_applied: list[str]) -> None:
    modules = {name: SimpleNamespace(operations=[]) for name in ("0001_a", "0002_b", "0003_c")}
    applied_by_infi: list[str] = []

    def apply_like_infi(database: Database, package_name: str, up_to: int, replicated: bool) -> None:
        # infi.clickhouse_orm's Database.migrate checks up_to only after applying a migration.
        for name in sorted(set(modules) - applied):
            applied_by_infi.append(name)
            if int(name[:4]) >= up_to:
                break

    with (
        responses.RequestsMock() as server,
        patch.object(Database, "migrate", autospec=True, side_effect=apply_like_infi),
        patch.object(Command, "get_applied_migrations", return_value=applied),
        patch("posthog.management.commands.migrate_clickhouse.import_submodules", return_value=modules),
        patch("posthog.management.commands.migrate_clickhouse.default_client"),
    ):
        server.add_callback(responses.POST, CLICKHOUSE_URL, callback=answer_server_query)
        Command().migrate(CLICKHOUSE_URL, {**APPLY_OPTIONS, "upto": upto})

    assert applied_by_infi == newly_applied
