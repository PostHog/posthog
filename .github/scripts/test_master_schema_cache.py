import subprocess
from pathlib import Path

import pytest

from master_schema_cache import MasterSchemaCache


def git(repository: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repository), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Schema check")
    git(tmp_path, "config", "user.email", "schema-check@example.com")
    git(tmp_path, "config", "core.hooksPath", "/dev/null")
    for filename, content in {
        "posthog/migrations/0001_initial.py": "initial = True",
        "posthog/migrations/0002_squashed.py": "replaces = [('posthog', '0001_initial')]",
        "posthog/clickhouse/migrations/0001_initial.py": "initial = True",
        "uv.lock": "version = 1",
        "docker-compose.base.yml": "services:\n    db:\n        image: postgres:15\n",
        "products/db_routing.yaml": "{}",
        "posthog/product_db_config.py": "config = {}",
        "posthog/product_db_router.py": "router = None",
        ".depot/workflows/ci-backend.yml": "env:\n    SCHEMA_CACHE_EPOCH: 'v2' # bump to abandon cached dumps\n",
    }.items():
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "baseline")
    git(tmp_path, "config", "uploadpack.allowFilter", "true")
    git(tmp_path, "remote", "add", "origin", str(tmp_path))
    return tmp_path


def test_key_matches_the_shell_key_other_workflows_restore(repository: Path) -> None:
    assert (
        MasterSchemaCache(repository).key(epoch="v2")
        == "posthog-schema-mig-v2-52d5a77f1c27d98c132143f281c4cde90dd58d74"
    )


@pytest.mark.parametrize(
    "filename,content,keep",
    [
        pytest.param(None, "", True, id="identical-schema-inputs"),
        pytest.param("posthog/migrations/0003_column.py", "new_column = True", True, id="added-column"),
        pytest.param("posthog/migrations/0001_initial.py", None, False, id="reverted-migration"),
        pytest.param("posthog/migrations/0002_squashed.py", "replaces = []", False, id="retired-squash"),
        pytest.param("products/db_routing.yaml", "new_product: separate", False, id="routing-change"),
        pytest.param(
            "docker-compose.base.yml", "services:\n    db:\n        image: postgres:16\n", False, id="postgres-change"
        ),
        pytest.param(
            "docker-compose.base.yml",
            "services:\n    db:\n        image: postgres:15\n    redis:\n        image: redis:7\n",
            True,
            id="unrelated-compose-change",
        ),
        pytest.param("uv.lock", "version = 2", False, id="dependency-change"),
        pytest.param("posthog/models.py", "unrelated = True", True, id="unrelated-source-change"),
        pytest.param("posthog/clickhouse/migrations/0001_initial.py", "changed = True", True, id="clickhouse-change"),
    ],
)
def test_validate_keeps_only_compatible_dumps(
    repository: Path, filename: str | None, content: str | None, keep: bool
) -> None:
    source = git(repository, "rev-parse", "HEAD")
    if filename is not None:
        path = repository / filename
        if content is None:
            path.unlink()
        else:
            path.write_text(content)
    git(repository, "add", ".")
    git(repository, "commit", "--allow-empty", "-qm", "checkout")
    dump = repository / "schema.sql.gz"
    dump.write_text("cached dump")

    assert MasterSchemaCache(repository).validate(key=f"posthog-schema-master-{source}", epoch="v2", dump=dump) is keep
    assert dump.exists() is keep


@pytest.mark.parametrize(
    "key,epoch",
    [
        pytest.param("posthog-schema-mig-v2-unmerged", "v2", id="unmerged-pr-cache"),
        pytest.param(f"posthog-schema-master-{'f' * 40}", "v2", id="unavailable-source"),
        pytest.param(None, "v3", id="different-epoch"),
    ],
)
def test_validate_discards_unusable_snapshots(repository: Path, key: str | None, epoch: str) -> None:
    if key is None:
        key = f"posthog-schema-master-{git(repository, 'rev-parse', 'HEAD')}"
    dump = repository / "schema.sql.gz"
    dump.write_text("cached dump")

    assert MasterSchemaCache(repository).validate(key=key, epoch=epoch, dump=dump) is False
    assert not dump.exists()


def test_validate_fetches_source_in_shallow_checkout(repository: Path, tmp_path: Path) -> None:
    source = git(repository, "rev-parse", "HEAD")
    (repository / "posthog/migrations/0003_column.py").write_text("new_column = True")
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "add column")
    checkout = tmp_path / "checkout"
    git(repository, "clone", "-q", "--depth=1", repository.as_uri(), str(checkout))
    dump = repository / "schema.sql.gz"
    dump.write_text("cached dump")

    assert MasterSchemaCache(checkout).validate(key=f"posthog-schema-master-{source}", epoch="v2", dump=dump) is True
    assert dump.exists()
    assert "promisor" not in git(checkout, "config", "--list", "--local")
