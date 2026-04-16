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


class TestColumnDefOptionalFields:
    def test_codec(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              t:
                engine: MergeTree
                columns:
                  - name: id
                    type: String
                    codec: ZSTD(1)
                order_by: [id]
            """,
        )
        state = parse_desired_state(f)
        assert state.tables["t"].columns[0].codec == "ZSTD(1)"

    def test_default_kind_and_expression(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              t:
                engine: MergeTree
                columns:
                  - name: ts
                    type: DateTime
                    default_kind: DEFAULT
                    default_expression: now()
                order_by: [ts]
            """,
        )
        state = parse_desired_state(f)
        col = state.tables["t"].columns[0]
        assert col.default_kind == "DEFAULT"
        assert col.default_expression == "now()"

    def test_default_alias_for_default_expression(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              t:
                engine: MergeTree
                columns:
                  - name: ts
                    type: DateTime
                    default: now()
                order_by: [ts]
            """,
        )
        state = parse_desired_state(f)
        assert state.tables["t"].columns[0].default_expression == "now()"


class TestOnNodesCoercion:
    def test_string_coerced_to_list(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              t:
                engine: MergeTree
                columns:
                  - name: id
                    type: String
                on_nodes: DATA
                order_by: [id]
            """,
        )
        state = parse_desired_state(f)
        assert state.tables["t"].on_nodes == ["DATA"]

    def test_list_unchanged(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              t:
                engine: MergeTree
                columns:
                  - name: id
                    type: String
                on_nodes: [DATA, COORDINATOR]
                order_by: [id]
            """,
        )
        state = parse_desired_state(f)
        assert state.tables["t"].on_nodes == ["DATA", "COORDINATOR"]

    def test_null_defaults_to_all(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              t:
                engine: MergeTree
                columns:
                  - name: id
                    type: String
                on_nodes:
                order_by: [id]
            """,
        )
        state = parse_desired_state(f)
        assert state.tables["t"].on_nodes == ["ALL"]

    def test_empty_list_not_coerced_to_all(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              t:
                engine: MergeTree
                columns:
                  - name: id
                    type: String
                on_nodes: []
                order_by: [id]
            """,
        )
        state = parse_desired_state(f)
        # [] is an intentional "deploy nowhere" — must not become ["ALL"]
        assert state.tables["t"].on_nodes == []


class TestInheritanceEdgeCases:
    def test_chain_inheritance_a_to_b_to_c(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              grandparent:
                engine: MergeTree
                columns:
                  - name: id
                    type: String
              parent:
                engine: MergeTree
                columns: inherit grandparent
              child:
                engine: MergeTree
                columns: inherit parent
            """,
        )
        state = parse_desired_state(f)
        child = state.tables["child"]
        assert len(child.columns) == 1
        assert child.columns[0].name == "id"

    def test_inherit_from_unknown_table_raises(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              t:
                engine: MergeTree
                columns: inherit nonexistent
            """,
        )
        with pytest.raises(ValueError, match="nonexistent"):
            parse_desired_state(f)

    def test_inherit_from_table_with_non_list_columns_raises(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              base:
                engine: MergeTree
                columns: not_an_inherit_string
              child:
                engine: MergeTree
                columns: inherit base
            """,
        )
        with pytest.raises(ValueError, match="no column list"):
            parse_desired_state(f)

    def test_columns_wrong_type_raises(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              t:
                engine: MergeTree
                columns: 42
            """,
        )
        with pytest.raises(ValueError, match="columns"):
            parse_desired_state(f)


class TestKafkaSettings:
    def test_integer_values_coerced_to_strings(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              kafka_t:
                engine: Kafka
                columns:
                  - name: msg
                    type: String
                settings:
                  kafka_num_consumers: 4
                  kafka_max_block_size: 65536
                  kafka_topic_list: events
            """,
        )
        state = parse_desired_state(f)
        settings = state.tables["kafka_t"].settings
        assert settings == {
            "kafka_num_consumers": "4",
            "kafka_max_block_size": "65536",
            "kafka_topic_list": "events",
        }


class TestMaterializedView:
    def test_target_and_select_stored(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              mv_t:
                engine: MaterializedView
                columns: []
                target: dest_table
                select: "SELECT id FROM src_table"
            """,
        )
        state = parse_desired_state(f)
        t = state.tables["mv_t"]
        assert t.target == "dest_table"
        assert t.select == "SELECT id FROM src_table"


class TestDictionaryEngine:
    def test_dict_fields_parsed(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              rate_dict:
                engine: Dictionary
                columns:
                  - name: currency
                    type: String
                primary_key: currency
                source:
                  type: CLICKHOUSE
                  table: raw_rates
                layout:
                  type: COMPLEX_KEY_HASHED
                lifetime:
                  min: 3000
                  max: 3600
                range:
                  min: start_date
                  max: end_date
            """,
        )
        state = parse_desired_state(f)
        t = state.tables["rate_dict"]
        assert t.engine == "Dictionary"
        assert t.primary_key == "currency"
        assert t.dict_source == {"type": "CLICKHOUSE", "table": "raw_rates"}
        assert t.dict_layout == {"type": "COMPLEX_KEY_HASHED"}
        assert t.dict_lifetime == {"min": 3000, "max": 3600}
        assert t.dict_range == {"min": "start_date", "max": "end_date"}
        # source string field must not be contaminated by the dict mapping
        assert t.source is None

    def test_dict_lifetime_values_coerced_to_int(self, tmp_path):
        f = _write_yaml(
            tmp_path,
            """
            ecosystem: events
            tables:
              d:
                engine: Dictionary
                columns: []
                source:
                  type: CLICKHOUSE
                  table: t
                layout:
                  type: FLAT
                lifetime:
                  min: "100"
                  max: "200"
            """,
        )
        state = parse_desired_state(f)
        lt = state.tables["d"].dict_lifetime
        assert lt == {"min": 100, "max": 200}


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
