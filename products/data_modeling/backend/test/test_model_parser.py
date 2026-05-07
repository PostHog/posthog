from textwrap import dedent

import pytest

from products.data_modeling.backend.services.gitsync.model_parser import (
    model_name_from_path,
    parse_model_file,
    serialize_model_file,
)


class TestParseModelFile:
    def test_bare_sql(self):
        result = parse_model_file("SELECT 1")
        assert result.query == "SELECT 1"
        assert result.description == ""
        assert result.materialized is False
        assert result.tags == []

    def test_multiline_query(self):
        content = dedent("""\
            SELECT
                id,
                name
            FROM users
            WHERE active = true
        """)
        result = parse_model_file(content)
        assert "SELECT" in result.query
        assert "FROM users" in result.query

    def test_materialize_directive(self):
        content = dedent("""\
            -- @materialize
            SELECT 1
        """)
        result = parse_model_file(content)
        assert result.materialized is True

    def test_view_directive(self):
        content = dedent("""\
            -- @view
            SELECT 1
        """)
        result = parse_model_file(content)
        assert result.materialized is False

    def test_description_directive(self):
        content = dedent("""\
            -- @description Monthly active users
            SELECT 1
        """)
        result = parse_model_file(content)
        assert result.description == "Monthly active users"

    @pytest.mark.parametrize(
        "desc",
        [
            '" monthly active users "',
            ' " monthly active users " ',
            " ' monthly active users ' ",
            "' monthly active users '",
        ],
    )
    def test_description_quoted(self, desc):
        content = dedent(f"""\
            -- @description {desc}
            SELECT 1
        """)
        result = parse_model_file(content)
        assert result.description == "monthly active users"

    def test_tags_directive(self):
        content = dedent("""\
            -- @tags marketing, finance, core
            SELECT 1
        """)
        result = parse_model_file(content)
        assert result.tags == ["marketing", "finance", "core"]

    def test_tags_single(self):
        content = dedent("""\
            -- @tags revenue
            SELECT 1
        """)
        result = parse_model_file(content)
        assert result.tags == ["revenue"]

    def test_all_annotations(self):
        content = dedent("""\
            -- @description Revenue by plan
            -- @materialize
            -- @tags revenue, core
            SELECT plan, sum(amount) FROM payments GROUP BY plan
        """)
        result = parse_model_file(content)
        assert result.description == "Revenue by plan"
        assert result.materialized is True
        assert result.tags == ["revenue", "core"]
        assert "SELECT plan" in result.query

    def test_shorthand_desc(self):
        content = dedent("""\
            -- @desc My description
            SELECT 1
        """)
        result = parse_model_file(content)
        assert result.description == "My description"

    def test_shorthand_mat(self):
        content = dedent("""\
            -- @mat
            SELECT 1
        """)
        result = parse_model_file(content)
        assert result.materialized is True

    def test_annotations_between_comments(self):
        content = dedent("""\
            -- @description Test model
            -- This is a regular comment
            SELECT 1
        """)
        result = parse_model_file(content)
        assert result.description == "Test model"
        assert "-- This is a regular comment" in result.query

    def test_preserves_non_annotation_comments(self):
        content = dedent("""\
            -- regular comment at top
            SELECT 1
            -- inline comment
        """)
        result = parse_model_file(content)
        assert "-- regular comment at top" in result.query
        assert "-- inline comment" in result.query


class TestParseModelFileValidation:
    def test_empty_query_raises(self):
        with pytest.raises(ValueError, match="no SQL query"):
            parse_model_file("-- @materialize")

    def test_only_annotations_raises(self):
        content = dedent("""\
            -- @materialize
            -- @description Foo
        """)
        with pytest.raises(ValueError, match="no SQL query"):
            parse_model_file(content)

    def test_unknown_annotation_raises(self):
        content = dedent("""\
            -- @bogus
            SELECT 1
        """)
        with pytest.raises(ValueError, match="unknown annotation @bogus"):
            parse_model_file(content)

    def test_unknown_annotation_reports_line_number(self):
        content = dedent("""\
            SELECT 1
            -- @nope
        """)
        with pytest.raises(ValueError, match="Line 2"):
            parse_model_file(content)

    @pytest.mark.parametrize(
        "first, second",
        [
            pytest.param("materialize", "view", id="materialize_then_view"),
            pytest.param("view", "materialize", id="view_then_materialize"),
        ],
    )
    def test_mutually_exclusive_materialize_view(self, first: str, second: str):
        content = f"-- @{first}\n-- @{second}\nSELECT 1\n"
        with pytest.raises(ValueError, match="Conflicting annotations"):
            parse_model_file(content)

    def test_duplicate_description_raises(self):
        content = dedent("""\
            -- @description First
            -- @description Second
            SELECT 1
        """)
        with pytest.raises(ValueError, match="duplicate @description"):
            parse_model_file(content)

    def test_duplicate_materialize_raises(self):
        content = dedent("""\
            -- @materialize
            -- @materialize
            SELECT 1
        """)
        with pytest.raises(ValueError, match="duplicate @materialize"):
            parse_model_file(content)

    def test_duplicate_tags_raises(self):
        content = dedent("""\
            -- @tags foo
            -- @tags bar
            SELECT 1
        """)
        with pytest.raises(ValueError, match="duplicate @tags"):
            parse_model_file(content)

    def test_description_empty_raises(self):
        content = dedent("""\
            -- @description
            SELECT 1
        """)
        with pytest.raises(ValueError, match="@description requires a value"):
            parse_model_file(content)

    def test_description_empty_quotes_raises(self):
        content = dedent("""\
            -- @description ""
            SELECT 1
        """)
        with pytest.raises(ValueError, match="@description requires a value"):
            parse_model_file(content)

    def test_tags_empty_raises(self):
        content = dedent("""\
            -- @tags
            SELECT 1
        """)
        with pytest.raises(ValueError, match="@tags requires a value"):
            parse_model_file(content)

    def test_nullary_with_value_raises(self):
        content = dedent("""\
            -- @materialize true
            SELECT 1
        """)
        with pytest.raises(ValueError, match="@materialize takes no value"):
            parse_model_file(content)

    def test_view_with_value_raises(self):
        content = dedent("""\
            -- @view ephemeral
            SELECT 1
        """)
        with pytest.raises(ValueError, match="@view takes no value"):
            parse_model_file(content)


class TestSerializeModelFile:
    def test_bare_query(self):
        result = serialize_model_file("SELECT 1")
        assert result == "SELECT 1\n"

    def test_with_description(self):
        result = serialize_model_file("SELECT 1", description="Test model")
        assert "-- @description Test model" in result
        assert "SELECT 1" in result

    def test_with_materialize(self):
        result = serialize_model_file("SELECT 1", materialized=True)
        assert "-- @materialize" in result

    def test_with_tags(self):
        result = serialize_model_file("SELECT 1", tags=["revenue", "core"])
        assert "-- @tags revenue, core" in result

    def test_all_annotations(self):
        result = serialize_model_file(
            "SELECT 1",
            description="Test",
            materialized=True,
            tags=["a", "b"],
        )
        assert "-- @description Test" in result
        assert "-- @materialize" in result
        assert "-- @tags a, b" in result

    def test_roundtrip(self):
        original = dedent("""\
            -- @description Revenue by plan
            -- @materialize
            -- @tags revenue, core
            SELECT plan, sum(amount) FROM payments GROUP BY plan
        """)
        parsed = parse_model_file(original)
        # query now includes annotations, so re-parsing should be stable
        reparsed = parse_model_file(parsed.query)
        assert reparsed.query == parsed.query
        assert reparsed.description == parsed.description
        assert reparsed.materialized == parsed.materialized
        assert reparsed.tags == parsed.tags


class TestModelNameFromPath:
    @pytest.mark.parametrize(
        "path,expected",
        [
            ("models/monthly_active_users.sql", "monthly_active_users"),
            ("models/staging/stg_events.sql", "stg_events"),
            ("environments/production/models/revenue.sql", "revenue"),
            ("revenue.sql", "revenue"),
            ("models/deep/nested/dir/my_model.sql", "my_model"),
        ],
    )
    def test_extracts_name(self, path, expected):
        assert model_name_from_path(path) == expected
