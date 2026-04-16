import textwrap
from pathlib import Path

import pytest

from posthog.clickhouse.migration_tools.desired_state import parse_desired_state, parse_desired_state_dir


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

    @pytest.mark.parametrize(
        "content,match",
        [
            ("tables: {}\n", "ecosystem"),
            (
                """
                ecosystem: events
                tables:
                  bad_table:
                    columns: []
                """,
                "engine",
            ),
        ],
    )
    def test_missing_required_field_raises(self, tmp_path, content, match):
        f = _write_yaml(tmp_path, content)
        with pytest.raises(ValueError, match=match):
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


class TestParseDesiredStateDir:
    def test_happy_path_returns_both_states(self, tmp_path):
        (tmp_path / "events.yaml").write_text("ecosystem: events\ntables: {}\n")
        (tmp_path / "sessions.yml").write_text("ecosystem: sessions\ntables: {}\n")
        states = parse_desired_state_dir(tmp_path)
        assert len(states) == 2
        ecosystems = {s.ecosystem for s in states}
        assert ecosystems == {"events", "sessions"}

    def test_yaml_and_yml_extensions_both_included(self, tmp_path):
        (tmp_path / "a.yaml").write_text("ecosystem: a\ntables: {}\n")
        (tmp_path / "b.yml").write_text("ecosystem: b\ntables: {}\n")
        states = parse_desired_state_dir(tmp_path)
        assert len(states) == 2

    def test_empty_dir_returns_empty_list(self, tmp_path):
        states = parse_desired_state_dir(tmp_path)
        assert states == []
