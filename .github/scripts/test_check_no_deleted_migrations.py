import io

import pytest

import check_no_deleted_migrations as guard


@pytest.mark.parametrize(
    "path,expected",
    [
        ("posthog/migrations/0001_initial.py", True),
        ("ee/migrations/0042_thing.py", True),
        ("products/tasks/backend/migrations/0003_x.py", True),
        ("posthog/rbac/migrations/0005_y.py", True),
        ("posthog/migrations/__init__.py", False),
        ("posthog/clickhouse/migrations/0099_x.py", False),
        ("posthog/async_migrations/migrations/0005_y.py", False),
        ("posthog/migrations/0001_initial.txt", False),
        ("products/tasks/backend/views.py", False),
        ("frontend/src/scenes/notebooks/Notebook/migrations/meta.ts", False),
    ],
)
def test_is_django_migration(path, expected):
    assert guard.is_django_migration(path) is expected


def test_load_allowlist_ignores_comments_and_blanks(tmp_path):
    f = tmp_path / "allow.txt"
    f.write_text(
        "# header comment\n"
        "\n"
        "posthog/migrations/0500_oops.py   # trailing comment\n"
        "  products/old/backend/migrations/  \n"
    )
    assert guard.load_allowlist(f) == [
        "posthog/migrations/0500_oops.py",
        "products/old/backend/migrations/",
    ]


def test_load_allowlist_missing_file_is_empty(tmp_path):
    assert guard.load_allowlist(tmp_path / "nope.txt") == []


@pytest.mark.parametrize(
    "path,allowlist,expected",
    [
        ("posthog/migrations/0500_oops.py", ["posthog/migrations/0500_oops.py"], True),
        ("products/old/backend/migrations/0001_initial.py", ["products/old/backend/migrations/"], True),
        ("products/old_v2/backend/migrations/0001_initial.py", ["products/old/backend/migrations/"], False),
        ("posthog/migrations/0500_oops.py", [], False),
    ],
)
def test_is_allowlisted(path, allowlist, expected):
    assert guard.is_allowlisted(path, allowlist) is expected


def test_guarded_deletions_filters_and_respects_allowlist():
    paths = [
        "posthog/migrations/0001_initial.py",
        "posthog/migrations/__init__.py",
        "posthog/clickhouse/migrations/0099_x.py",
        "products/old/backend/migrations/0001_x.py",
        "frontend/app.ts",
    ]
    allowlist = ["products/old/backend/migrations/"]
    assert guard.guarded_deletions(paths, allowlist) == ["posthog/migrations/0001_initial.py"]


def test_main_stdin_blocks_historical(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(guard, "ALLOWLIST_PATH", tmp_path / "none.txt")
    monkeypatch.setattr("sys.stdin", io.StringIO("posthog/migrations/0001_initial.py\nfrontend/x.ts\n"))
    assert guard.main(["check", "--stdin"]) == 1
    assert "refusing to delete" in capsys.readouterr().err


def test_main_stdin_clean_passes(monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "ALLOWLIST_PATH", tmp_path / "none.txt")
    monkeypatch.setattr("sys.stdin", io.StringIO("posthog/migrations/__init__.py\nfrontend/app.ts\n"))
    assert guard.main(["check", "--stdin"]) == 0


def test_main_rejects_unknown_mode():
    assert guard.main(["check", "--bogus"]) == 2
