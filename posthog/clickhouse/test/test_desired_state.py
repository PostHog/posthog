import textwrap
from pathlib import Path

import pytest

from posthog.clickhouse.migration_tools.desired_state import parse_desired_state


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "schema.yaml"
    p.write_text(textwrap.dedent(content))
    return p


class TestParseDesiredState:
    def test_basic_parsing(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            cluster: main
            tables:
              my_table:
                engine: MergeTree
                columns:
                  - name: id
                    type: String
                order_by: [id]
            """,
        )
        state = parse_desired_state(f)
        assert state.ecosystem == "events"
        assert state.cluster == "main"
        assert "my_table" in state.tables
        table = state.tables["my_table"]
        assert table.engine == "MergeTree"
        assert len(table.columns) == 1
        assert table.columns[0].name == "id"

    def test_default_cluster_and_database(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: logs
            tables: {}
            """,
        )
        state = parse_desired_state(f)
        assert state.cluster == "main"
        assert state.database == "posthog"

    def test_missing_ecosystem_raises(self, tmp_path):
        f = _write_yaml(tmp_path, "tables: {}\n")
        with pytest.raises(ValueError, match="ecosystem"):
            parse_desired_state(f)

    def test_missing_engine_raises(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              bad_table:
                columns: []
            """,
        )
        with pytest.raises(ValueError, match="engine"):
            parse_desired_state(f)


class TestCircularInheritance:
    def test_circular_inheritance_raises(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              table_a:
                engine: MergeTree
                columns: inherit table_b
              table_b:
                engine: MergeTree
                columns: inherit table_a
            """,
        )
        with pytest.raises(ValueError, match="[Cc]ircular"):
            parse_desired_state(f)

    def test_valid_inheritance(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              base_table:
                engine: MergeTree
                columns:
                  - name: id
                    type: String
              child_table:
                engine: MergeTree
                columns: inherit base_table
            """,
        )
        state = parse_desired_state(f)
        child = state.tables["child_table"]
        assert len(child.columns) == 1
        assert child.columns[0].name == "id"
