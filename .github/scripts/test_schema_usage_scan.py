"""Tests for the posthog.schema AST dependency scanner.

Run with: uv run --with pytest pytest .github/scripts/test_schema_usage_scan.py
"""

import textwrap
from pathlib import Path

from schema_usage_scan import scan


def write_py(root: Path, product: str, name: str, content: str) -> None:
    path = root / product / "backend" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip())


def test_direct_symbol_import(tmp_path: Path) -> None:
    write_py(tmp_path, "logs", "a.py", "from posthog.schema import LogsQuery, HogQLFilters\n")
    result = scan(str(tmp_path))
    assert result == {"HogQLFilters": ["logs"], "LogsQuery": ["logs"]}


def test_direct_import_uses_original_name_not_alias(tmp_path: Path) -> None:
    write_py(tmp_path, "logs", "a.py", "from posthog.schema import LogsQuery as LQ\nq = LQ()\n")
    result = scan(str(tmp_path))
    assert result == {"LogsQuery": ["logs"]}


def test_schema_enums_symbol_import(tmp_path: Path) -> None:
    write_py(tmp_path, "logs", "a.py", "from posthog.schema_enums import ProductKey\n")
    result = scan(str(tmp_path))
    assert result == {"ProductKey": ["logs"]}


def test_import_posthog_schema_enums_dotted(tmp_path: Path) -> None:
    write_py(tmp_path, "logs", "a.py", "import posthog.schema_enums\nk = posthog.schema_enums.ProductKey\n")
    result = scan(str(tmp_path))
    assert result == {"ProductKey": ["logs"]}


def test_star_import_is_wildcard(tmp_path: Path) -> None:
    write_py(tmp_path, "logs", "a.py", "from posthog.schema import *\n")
    assert scan(str(tmp_path)) == {"*": ["logs"]}


def test_from_posthog_import_schema_attribute_refs(tmp_path: Path) -> None:
    write_py(
        tmp_path,
        "product_analytics",
        "b.py",
        """
        from posthog import schema

        def build(node: schema.InsightVizNode) -> schema.DataVisualizationNode:
            return schema.DataVisualizationNode()
        """,
    )
    result = scan(str(tmp_path))
    assert result == {
        "DataVisualizationNode": ["product-analytics"],
        "InsightVizNode": ["product-analytics"],
    }


def test_from_posthog_import_schema_aliased(tmp_path: Path) -> None:
    write_py(tmp_path, "logs", "b.py", "from posthog import schema as sch\nq = sch.TrendsQuery()\n")
    assert scan(str(tmp_path)) == {"TrendsQuery": ["logs"]}


def test_import_posthog_schema_dotted(tmp_path: Path) -> None:
    write_py(tmp_path, "alerts", "c.py", 'import posthog.schema\ns = posthog.schema.AlertState["FIRING"]\n')
    assert scan(str(tmp_path)) == {"AlertState": ["alerts"]}


def test_import_posthog_schema_aliased(tmp_path: Path) -> None:
    write_py(tmp_path, "logs", "c.py", "import posthog.schema as ps\nx: ps.HogQLQuery = ps.HogQLQuery()\n")
    assert scan(str(tmp_path)) == {"HogQLQuery": ["logs"]}


def test_import_posthog_package_dotted(tmp_path: Path) -> None:
    write_py(tmp_path, "alerts", "c.py", "import posthog\nx = posthog.schema.AlertState\n")
    assert scan(str(tmp_path)) == {"AlertState": ["alerts"]}


def test_nested_attribute_records_type_not_member(tmp_path: Path) -> None:
    write_py(tmp_path, "logs", "b.py", "from posthog import schema\nv = schema.AlertState.FIRING\n")
    assert scan(str(tmp_path)) == {"AlertState": ["logs"]}


def test_dynamic_use_of_module_is_wildcard(tmp_path: Path) -> None:
    write_py(tmp_path, "mystery", "d.py", "from posthog import schema\nregister(schema)\n")
    assert scan(str(tmp_path)) == {"*": ["mystery"]}


def test_reassigned_module_binding_is_wildcard(tmp_path: Path) -> None:
    write_py(tmp_path, "mystery", "d.py", "from posthog import schema\ns = schema\nx = s.LogsQuery\n")
    result = scan(str(tmp_path))
    assert result["*"] == ["mystery"]


def test_comments_and_strings_do_not_match(tmp_path: Path) -> None:
    write_py(
        tmp_path,
        "logs",
        "a.py",
        '''
        # from posthog import schema  -> schema.LogsQuery
        """Docstring mentioning schema.TrendsQuery should be ignored."""
        x = "from posthog.schema import EventsQuery"
        ''',
    )
    assert scan(str(tmp_path)) == {}


def test_unrelated_schema_attribute_not_matched(tmp_path: Path) -> None:
    write_py(
        tmp_path,
        "logs",
        "a.py",
        """
        from posthog import schema

        config.schema.something  # unrelated object, must not leak `something`
        real = schema.LogsQuery
        """,
    )
    assert scan(str(tmp_path)) == {"LogsQuery": ["logs"]}


def test_syntax_error_is_wildcard(tmp_path: Path) -> None:
    write_py(tmp_path, "broken", "a.py", "from posthog import schema\ndef oops(:\n")
    assert scan(str(tmp_path)) == {"*": ["broken"]}


def test_file_without_schema_is_skipped(tmp_path: Path) -> None:
    write_py(tmp_path, "logs", "a.py", "import os\nfrom posthog.models import Team\n")
    assert scan(str(tmp_path)) == {}


def test_unioned_across_products_and_sorted(tmp_path: Path) -> None:
    write_py(tmp_path, "surveys", "a.py", "from posthog.schema import LogsQuery\n")
    write_py(tmp_path, "logs", "b.py", "from posthog import schema\nx = schema.LogsQuery\n")
    assert scan(str(tmp_path)) == {"LogsQuery": ["logs", "surveys"]}
