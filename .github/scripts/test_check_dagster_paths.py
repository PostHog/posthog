import textwrap
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("check-dagster-paths.py")
SPEC = importlib.util.spec_from_file_location("check_dagster_paths", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
check_dagster_paths = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_dagster_paths)


def write_file(root: Path, relative_path: str, content: str = "") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip())
    return path


@pytest.mark.parametrize(
    "pattern,path,expected",
    [
        pytest.param("posthog/**/*.py", "posthog/schema.py", True, id="posthog-py-direct"),
        pytest.param("posthog/**/*.py", "posthog/dags/common/resources.py", True, id="posthog-py-nested"),
        pytest.param("posthog/**/*.py", "products/growth/backend/models.py", False, id="posthog-py-non-match"),
        pytest.param("posthog/clickhouse/**", "posthog/clickhouse/query_tagging.py", True, id="clickhouse-direct"),
        pytest.param("posthog/clickhouse/**", "posthog/clickhouse/client/connection.py", True, id="clickhouse-nested"),
        pytest.param("posthog/clickhouse/**", "posthog/hogql/query.py", False, id="clickhouse-non-match"),
        pytest.param(
            "products/*/backend/models/**",
            "products/growth/backend/models/oauth.py",
            True,
            id="product-models-single-segment",
        ),
        pytest.param(
            "products/*/backend/models/**",
            "products/revenue_analytics/backend/models/exchange/rate.py",
            True,
            id="product-models-nested",
        ),
        pytest.param(
            "products/*/backend/models/**",
            "products/growth/dags/oauth.py",
            False,
            id="product-models-non-match",
        ),
        pytest.param("posthog/schema.py", "posthog/schema.py", True, id="exact-file-match"),
        pytest.param("posthog/schema.py", "posthog/schema.pyi", False, id="exact-file-non-match"),
    ],
)
def test_glob_to_regex(pattern: str, path: str, expected: bool) -> None:
    regex = check_dagster_paths.glob_to_regex(pattern)

    assert bool(regex.match(path)) is expected


@pytest.mark.parametrize(
    "content,expected",
    [
        pytest.param("import posthog.schema\n", {"posthog.schema"}, id="import"),
        pytest.param(
            "from posthog.schema import ProductKey\n",
            {"posthog.schema", "posthog.schema.ProductKey"},
            id="from-import-attribute",
        ),
        pytest.param(
            "from posthog.hogql import query\n",
            {"posthog.hogql", "posthog.hogql.query"},
            id="from-import-submodule",
        ),
        pytest.param(
            "from posthog.hogql.query import execute_hogql_query\n",
            {"posthog.hogql.query", "posthog.hogql.query.execute_hogql_query"},
            id="from-nested-import",
        ),
        pytest.param("from .local import thing\nfrom ..pkg import other\n", set(), id="relative-imports-ignored"),
    ],
)
def test_extract_imports(tmp_path: Path, content: str, expected: set[str]) -> None:
    path = write_file(tmp_path, "example.py", content)

    assert check_dagster_paths.extract_imports(path) == expected


@pytest.mark.parametrize(
    "module_name,expected",
    [
        pytest.param("posthog.schema", "posthog/schema.py", id="top-level-file"),
        pytest.param("posthog.models", "posthog/models/__init__.py", id="package-init"),
        pytest.param("common.utils", "common/utils/__namespace_probe__.py", id="namespace-package"),
        pytest.param("posthog.utils.foo", "posthog/utils.py", id="attribute-walk-up"),
    ],
)
def test_resolve_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module_name: str, expected: str) -> None:
    write_file(tmp_path, "posthog/schema.py")
    write_file(tmp_path, "posthog/models/__init__.py")
    write_file(tmp_path, "posthog/utils.py", "foo = 1\n")
    write_file(tmp_path, "common/utils/helpers.py")
    monkeypatch.setattr(check_dagster_paths, "REPO_ROOT", tmp_path)

    assert check_dagster_paths.resolve_module(module_name) == Path(expected)


def test_find_dag_files_includes_ee_billing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_file(tmp_path, "posthog/dags/posthog_job.py")
    write_file(tmp_path, "products/growth/dags/growth_job.py")
    write_file(tmp_path, "ee/billing/dags/billing_job.py")
    monkeypatch.setattr(check_dagster_paths, "REPO_ROOT", tmp_path)

    assert sorted(path.relative_to(tmp_path).as_posix() for path in check_dagster_paths.find_dag_files()) == [
        "ee/billing/dags/billing_job.py",
        "posthog/dags/posthog_job.py",
        "products/growth/dags/growth_job.py",
    ]


def test_main_reports_only_uncovered_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dag_file = write_file(
        tmp_path,
        "posthog/dags/example.py",
        """
        import posthog.schema
        import posthog.utils
        """,
    )
    write_file(tmp_path, "posthog/schema.py")
    write_file(tmp_path, "posthog/utils.py")
    monkeypatch.setattr(check_dagster_paths, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_dagster_paths, "find_dag_files", lambda: [dag_file])
    monkeypatch.setattr(check_dagster_paths, "load_filter_patterns", lambda: ["posthog/utils.py"])

    result = check_dagster_paths.main()
    output = capsys.readouterr().out

    assert result == 1
    assert "posthog.schema  →  posthog/schema.py" in output
    assert "imported by posthog/dags/example.py" in output
    assert "posthog.utils" not in output


def test_main_reports_missing_dependency_from_ee_billing_dags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_file(
        tmp_path,
        "posthog/dags/locations/billing.py",
        "from ee.billing.dags.customer_archetype import job\n",
    )
    ee_billing_dag = write_file(
        tmp_path,
        "ee/billing/dags/customer_archetype.py",
        "from posthog.llm.gateway_client import get_llm_client\n",
    )
    write_file(tmp_path, "posthog/llm/gateway_client.py")
    monkeypatch.setattr(check_dagster_paths, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_dagster_paths, "find_dag_files", lambda: [ee_billing_dag])
    monkeypatch.setattr(check_dagster_paths, "load_filter_patterns", lambda: ["ee/billing/**"])

    result = check_dagster_paths.main()
    output = capsys.readouterr().out

    assert result == 1
    assert "posthog.llm.gateway_client  →  posthog/llm/gateway_client.py" in output
    assert "imported by ee/billing/dags/customer_archetype.py" in output
