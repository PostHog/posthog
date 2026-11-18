import sys
import subprocess
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("check-new-events-schema-targets.py")
SPEC = importlib.util.spec_from_file_location("check_new_events_schema_targets", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

MODULE = "products/growth/backend/team_sdk_versions.py"
TEST = "products/growth/backend/tests/test_team_sdk_versions.py"
BASE_SOURCE = "def get_sdk_versions_for_team(team):\n    return run_query(EVENTS_QUERY)\n"
BRANCHED_SOURCE = (
    "from products.feature_flags.backend.facade.flags import flag_calls_only_in_flag_evaluations\n\n"
    "def get_sdk_versions_for_team(team):\n"
    "    query = EVENTS_AND_FLAG_EVALUATIONS_QUERY if flag_calls_only_in_flag_evaluations(team) else EVENTS_QUERY\n"
    "    return run_query(query)\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _write(repo: Path, path: str, text: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(repo, check.TARGETS_FILE, "# HogQL\nposthog/hogql/  # trailing slash\n")
    _write(repo, MODULE, BASE_SOURCE)
    _write(repo, TEST, "from products.growth.backend.team_sdk_versions import get_sdk_versions_for_team\n")
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    monkeypatch.chdir(repo)
    return repo


def _commit(repo: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        _write(repo, path, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")


def _main(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["check-new-events-schema-targets.py", "--against", "master", "--committed"])
    return check.main()


def test_new_branch_with_an_unlisted_importing_test_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _commit(repo, {MODULE: BRANCHED_SOURCE})

    assert _main(monkeypatch) == 1
    out = capsys.readouterr().out
    assert f"  {MODULE}\n    {TEST}\n" in out
    assert check.LABEL in out


@pytest.mark.parametrize(
    "_name,changes,routing_only",
    [
        ("test_listed_by_file", {MODULE: BRANCHED_SOURCE, check.TARGETS_FILE: f"posthog/hogql\n{TEST}\n"}, {}),
        (
            "test_listed_by_directory",
            {MODULE: BRANCHED_SOURCE, check.TARGETS_FILE: "products/growth/backend/tests/\n"},
            {},
        ),
        (
            "test_only_patches_the_module",
            {MODULE: BRANCHED_SOURCE, TEST: '@patch("products.growth.backend.team_sdk_versions.run_query")\n'},
            {},
        ),
        ("module_routes_only", {MODULE: BRANCHED_SOURCE}, {MODULE: "picks a route"}),
        (
            "branch_added_to_a_test_helper",
            {
                "products/growth/backend/tests/helpers.py": BRANCHED_SOURCE,
                TEST: "from products.growth.backend.tests.helpers import get_sdk_versions_for_team\n",
            },
            {},
        ),
        (
            "branch_added_to_a_settings_module",
            {
                "posthog/settings/data_stores.py": BRANCHED_SOURCE,
                TEST: "from posthog.settings.data_stores import get_sdk_versions_for_team\n",
            },
            {},
        ),
    ],
)
def test_new_branch_passes(
    _name: str, changes: dict[str, str], routing_only: dict[str, str], repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check, "ROUTING_ONLY", routing_only)
    _commit(repo, changes)

    assert _main(monkeypatch) == 0


@pytest.mark.parametrize(
    "module,test,test_source",
    [
        (MODULE, TEST, "from ..team_sdk_versions import get_sdk_versions_for_team\n"),
        (
            "products/growth/backend/sdk/__init__.py",
            "products/growth/backend/sdk/tests/test_sdk.py",
            "from .. import get_sdk_versions_for_team\n",
        ),
    ],
)
def test_test_importing_through_a_relative_import_is_named(
    module: str,
    test: str,
    test_source: str,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _commit(repo, {module: BRANCHED_SOURCE, test: test_source})

    assert _main(monkeypatch) == 1
    assert test in capsys.readouterr().out


def test_swapping_one_branch_for_another_fails(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _commit(repo, {MODULE: BRANCHED_SOURCE})
    _git(repo, "branch", "-f", "master")
    swapped = BRANCHED_SOURCE.replace("flag_calls_only_in_flag_evaluations(team)", "use_new_events_schema(team.pk)")
    _commit(repo, {MODULE: swapped})

    assert _main(monkeypatch) == 1


@pytest.mark.parametrize("extra_lines", [0, 40])
def test_moving_an_existing_branch_to_a_new_path_passes(
    extra_lines: int, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _commit(repo, {MODULE: BRANCHED_SOURCE})
    _git(repo, "branch", "-f", "master")
    _git(repo, "rm", "-q", MODULE)
    edited = BRANCHED_SOURCE + "".join(f"\n\ndef helper_{n}():\n    return {n}\n" for n in range(extra_lines))
    _commit(
        repo,
        {
            "products/growth/backend/sdk_versions.py": edited,
            TEST: "from products.growth.backend.sdk_versions import get_sdk_versions_for_team\n",
        },
    )

    assert _main(monkeypatch) == 0


@pytest.mark.parametrize("extra_lines", [0, 40])
@pytest.mark.parametrize(
    "old_path",
    [
        "products/growth/backend/tests/test_old_sdk_versions.py",
        "products/growth/backend/conftest.py",
        "products/growth/backend/tests/helpers.py",
        "posthog/settings/data_stores.py",
    ],
)
def test_branch_moved_out_of_a_non_production_file_fails(
    old_path: str, extra_lines: int, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _commit(repo, {old_path: BRANCHED_SOURCE})
    _git(repo, "branch", "-f", "master")
    _git(repo, "rm", "-q", old_path)
    edited = BRANCHED_SOURCE + "".join(f"\n\ndef helper_{n}():\n    return {n}\n" for n in range(extra_lines))
    _commit(
        repo,
        {
            "products/growth/backend/sdk_versions.py": edited,
            TEST: "from products.growth.backend.sdk_versions import get_sdk_versions_for_team\n",
        },
    )

    assert _main(monkeypatch) == 1


@pytest.mark.parametrize(
    "_name,source,expected",
    [
        ("helper_call", "if use_new_events_schema(team.pk):\n    pass", 1),
        ("flag_call_helper", "reads_flag_calls_from_flag_evaluations(team, modifiers)", 1),
        ("hogql_context_flag_method", "only = context.flag_calls_only_in_flag_evaluations()", 1),
        ("hogql_context_schema_method", "native = context.uses_new_events_schema()", 1),
        ("helper_passed_as_callable", "native = database_sync_to_async(use_new_events_schema)(team_id)", 1),
        ("django_setting", "if TEST and settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:\n    pass", 1),
        ("aliased_django_setting", "native = app_settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA", 1),
        ("instance_setting", 'native = get_instance_setting("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA")', 1),
        ("definition", "def use_new_events_schema(team_id=None):\n    pass", 0),
        ("wrapper_with_a_longer_name", "native = self._use_new_events_schema()", 0),
        ("import", "from posthog.models.event.new_events_schema import use_new_events_schema", 0),
        ("comment", "# use_new_events_schema(team) decides the table", 0),
        ("docstring", 'def f():\n    """use_new_events_schema(team) decides the table."""', 0),
        ("teams_setting", "native = settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", 0),
    ],
)
def test_schema_branches(_name: str, source: str, expected: int) -> None:
    assert check.schema_branches(source).total() == expected
