import sys
import textwrap
import subprocess
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("quarantine_base_check.py")
SPEC = importlib.util.spec_from_file_location("quarantine_base_check", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
qbc = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = qbc
SPEC.loader.exec_module(qbc)

PASSING = "def test_a():\n    assert True\n"
FAILING = "def test_a():\n    assert False\n"
SETTINGS = "PERSON_ON_EVENTS_V2_ENABLED=true\nCLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=false\nPYTEST_ARGS=\n"


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


class Scenario:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self.src = tmp_path / "src"
        self.root = tmp_path / "work"
        self.origin = tmp_path / "origin.git"
        self.out = tmp_path / "out"
        self.settings = tmp_path / "settings.env"
        self.settings.write_text(SETTINGS)
        self.junit = tmp_path / "junit-core.xml"
        self.src.mkdir()
        sh(tmp_path, "git", "init", "--bare", str(self.origin))
        sh(self.src, "git", "init", "-b", "master")
        sh(self.src, "git", "config", "user.email", "t@example.com")
        sh(self.src, "git", "config", "user.name", "t")
        sh(self.src, "git", "remote", "add", "origin", f"file://{self.origin}")
        monkeypatch.setattr(qbc, "BASE_PYTEST_FLAGS", ("-q",))
        monkeypatch.setattr(qbc, "RETRY_FLAGS", ())

    def write(self, files: dict[str, str]) -> None:
        for name, content in files.items():
            path = self.src / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        sh(self.src, "git", "add", "-A")
        sh(self.src, "git", "commit", "-m", "change")

    def build(self, base: dict[str, str], pr: dict[str, str], head: str = "merge") -> None:
        self.write({"pytest.ini": "[pytest]\njunit_family = xunit1\n", "posthog/conftest.py": "", **base})
        sh(self.src, "git", "push", "origin", "master")
        sh(self.src, "git", "checkout", "-b", "pr")
        self.write(pr)
        sh(self.src, "git", "push", "origin", "pr")
        sh(self.src, "git", "checkout", "master")
        sh(self.src, "git", "merge", "--no-ff", "-m", "merge", "pr")
        sh(self.src, "git", "push", "origin", "master:merge")
        # A shallow clone of the head, like the shard's checkout: the base commit is not local.
        sh(self.src, "git", "clone", "--depth", "1", "--branch", head, f"file://{self.origin}", str(self.root))
        # The shard's own pytest run on the head produces the report the gate masks.
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={self.junit}", "tests"],
            cwd=self.root,
            capture_output=True,
        )

    def run(self, cmd, env):
        argv = [sys.executable, "-m", "pytest", *cmd[1:]] if cmd[0] == "pytest" else list(cmd)
        return subprocess.run(argv, cwd=self.root, env=env, capture_output=True, text=True)

    def check(self, event: str = "pull_request") -> list[str]:
        return qbc.check(self.junit, self.settings, self.out, self.root, event, self.run)


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    return Scenario(tmp_path, monkeypatch)


def test_failure_that_also_fails_on_base_stays_masked(scenario):
    scenario.build({"tests/test_x.py": FAILING}, {"tests/test_y.py": PASSING})
    assert scenario.check() == []


def test_shard_settings_reach_the_base_run(scenario):
    fails_only_with_shard_setting = (
        "import os\n\n\ndef test_a():\n    assert os.environ.get('PERSON_ON_EVENTS_V2_ENABLED') != 'true'\n"
    )
    scenario.build({"tests/test_x.py": fails_only_with_shard_setting}, {"tests/test_x.py": FAILING})
    assert scenario.check() == []


def test_failure_that_passes_on_base_is_a_regression(scenario):
    scenario.build({"tests/test_x.py": PASSING}, {"tests/test_x.py": FAILING})
    assert scenario.check() == ["tests/test_x.py::test_a"]


def test_only_the_test_that_passes_on_base_is_reported(scenario):
    two = "def test_a():\n    assert {a}\n\n\ndef test_b():\n    assert {b}\n"
    scenario.build(
        {"tests/test_x.py": two.format(a="False", b="True")},
        {"tests/test_x.py": two.format(a="False", b="False")},
    )
    assert scenario.check() == ["tests/test_x.py::test_b"]


def test_class_and_parametrized_ids_resolve_to_exact_node_ids(scenario):
    code = textwrap.dedent(
        """
        import pytest

        class TestOuter:
            class TestInner:
                @pytest.mark.parametrize("value", ["a/b", "c d"])
                def test_p(self, value):
                    assert {ok}
        """
    )
    scenario.build({"tests/test_x.py": code.format(ok="True")}, {"tests/test_x.py": code.format(ok="False")})
    assert scenario.check() == [
        "tests/test_x.py::TestOuter::TestInner::test_p[a/b]",
        "tests/test_x.py::TestOuter::TestInner::test_p[c d]",
    ]


def test_test_that_is_new_in_the_pr_is_not_masked(scenario):
    scenario.build({"tests/test_x.py": PASSING}, {"tests/test_new.py": FAILING})
    with pytest.raises(qbc.CannotVerify, match="exited 4"):
        scenario.check()


SKIPPED = "import pytest\n\n\ndef test_a():\n    pytest.skip('no')\n"
TEARDOWN_ERROR = (
    "import pytest\n\n\n@pytest.fixture\ndef td():\n    yield\n    raise RuntimeError\n\n\n"
    "def test_a(td):\n    assert False\n"
)


@pytest.mark.parametrize("base_code", [SKIPPED, TEARDOWN_ERROR], ids=["skipped", "errors-in-teardown"])
def test_test_that_does_not_plainly_fail_on_base_is_not_masked(scenario, base_code):
    scenario.build({"tests/test_x.py": base_code}, {"tests/test_x.py": FAILING})
    assert scenario.check() == ["tests/test_x.py::test_a"]


def test_base_that_does_not_build_is_not_masked(scenario):
    scenario.build({"tests/test_x.py": "def test_a(:\n"}, {"tests/test_x.py": FAILING})
    with pytest.raises(qbc.CannotVerify, match="did not run the tests to a verdict"):
        scenario.check()


def test_base_that_cannot_be_fetched_is_not_masked(scenario):
    scenario.build({"tests/test_x.py": FAILING}, {"tests/test_y.py": PASSING})
    sh(scenario.root, "git", "remote", "set-url", "origin", f"file://{scenario.out}/missing.git")
    with pytest.raises(qbc.CannotVerify, match="git fetch"):
        scenario.check()


@pytest.mark.parametrize(
    "path",
    [
        "posthog/migrations/0001_x.py",
        "products/a/backend/migrations/0002_y.py",
        "migrations/0003_z.py",
        "rust/persons_migrations/0001_x.sql",
        "uv.lock",
        "products/a/pyproject.toml",
        ".python-version",
        "common/hogql_parser/HogQLParser.cpp",
        "rust/hogql/parser/src/lib.rs",
    ],
)
def test_pr_that_changes_the_database_or_packages_is_not_masked(scenario, path):
    scenario.build({"tests/test_x.py": FAILING}, {path: "x\n"})
    with pytest.raises(qbc.CannotVerify, match="reused database and packages"):
        scenario.check()


def test_head_that_is_not_a_merge_commit_is_not_masked(scenario):
    scenario.build({"tests/test_x.py": FAILING}, {"tests/test_y.py": PASSING}, head="pr")
    with pytest.raises(qbc.CannotVerify, match="not a merge commit"):
        scenario.check()


def test_setup_error_on_the_pr_is_not_masked(scenario):
    errors = (
        "import pytest\n\n\n@pytest.fixture\ndef boom():\n    raise RuntimeError\n\n\ndef test_a(boom):\n    pass\n"
    )
    scenario.build({"tests/test_x.py": errors}, {"tests/test_y.py": PASSING})
    with pytest.raises(qbc.CannotVerify, match="setup or teardown"):
        scenario.check()


def test_failed_shard_with_no_failing_test_in_the_report_is_not_masked(scenario):
    scenario.build({"tests/test_x.py": PASSING}, {"tests/test_y.py": PASSING})
    with pytest.raises(qbc.CannotVerify, match="lists no failing test"):
        scenario.check()


def test_missing_shard_settings_are_not_masked(scenario):
    scenario.build({"tests/test_x.py": FAILING}, {"tests/test_y.py": PASSING})
    scenario.settings.write_text("PYTEST_ARGS=\n")
    with pytest.raises(qbc.CannotVerify, match="lack"):
        scenario.check()


def test_report_that_cannot_be_read_is_not_masked(scenario):
    scenario.build({"tests/test_x.py": FAILING}, {"tests/test_y.py": PASSING})
    scenario.junit.unlink()
    with pytest.raises(qbc.CannotVerify, match="cannot read JUnit"):
        scenario.check()


@pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch", ""])
def test_event_without_a_base_keeps_the_gate_result(scenario, event):
    # Nothing is built: the check must return before it reads the report or touches git.
    assert scenario.check(event) == []


@pytest.mark.parametrize(
    "outcome,expected_exit",
    [([], 0), (["tests/test_x.py::test_a"], 1), (qbc.CannotVerify("x"), 1)],
    ids=["pre-existing", "regression", "cannot-verify"],
)
def test_main_exit_code_follows_the_check_result(monkeypatch, outcome, expected_exit):
    seen = {}

    def fake_check(*args):
        seen["event"] = args[4]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setattr(qbc, "check", fake_check)
    argv = ["--junit", "j.xml", "--settings", "s.env", "--out-dir", "out"]
    assert qbc.main(argv) == expected_exit
    assert seen["event"] == "pull_request"
