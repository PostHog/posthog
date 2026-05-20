from __future__ import annotations

import datetime

import pytest

from posthog.temporal.data_imports.sources.common.sql.identifiers import (
    AnsiIdentifierQuoter,
    BacktickIdentifierQuoter,
    InvalidIdentifierError,
)
from posthog.temporal.data_imports.sources.common.sql.query_builder import ParamStyle, SelectQueryBuilder

from products.data_warehouse.backend.types import IncrementalFieldType


class TestSelectAllFullRefresh:
    builder = SelectQueryBuilder(quoter=BacktickIdentifierQuoter())

    def test_builds_unqualified_select_with_backticks(self) -> None:
        result = self.builder.select_all(schema="mydb", table_name="messages")
        assert result.sql == "SELECT * FROM `mydb`.`messages`"
        assert result.params == {}

    def test_extra_hint_is_appended_verbatim(self) -> None:
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            extra_table_hint="FORCE INDEX (`idx_created_at`)",
        )
        assert "FORCE INDEX (`idx_created_at`)" in result.sql
        assert result.sql.startswith("SELECT * FROM `mydb`.`messages` FORCE INDEX")

    def test_injection_in_identifier_raises(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            self.builder.select_all(schema="mydb", table_name="messages; DROP TABLE x")


class TestSelectAllIncremental:
    builder = SelectQueryBuilder(quoter=BacktickIdentifierQuoter())

    def test_pyformat_named_placeholder_is_used_for_value(self) -> None:
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            incremental_last_value=datetime.datetime(2025, 1, 1),
        )
        assert "%(incremental_value)s" in result.sql
        assert "WHERE `created_at` > %(incremental_value)s" in result.sql
        assert "ORDER BY `created_at` ASC" in result.sql
        assert result.params == {"incremental_value": datetime.datetime(2025, 1, 1)}

    def test_value_never_interpolated_into_sql(self) -> None:
        """SQL-injection guard: the value string must stay in params."""
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            incremental_last_value="2025'; DROP TABLE x; --",
        )
        assert "DROP TABLE" not in result.sql
        assert result.params == {"incremental_value": "2025'; DROP TABLE x; --"}

    def test_initial_value_used_when_last_value_is_none(self) -> None:
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.Integer,
            incremental_last_value=None,
        )
        assert isinstance(result.params, dict)
        assert result.params["incremental_value"] == 0

    def test_incremental_field_type_required(self) -> None:
        with pytest.raises(ValueError, match="incremental_field_type is required"):
            self.builder.select_all(
                schema="mydb",
                table_name="messages",
                incremental_field="created_at",
                incremental_field_type=None,
            )

    def test_date_type_uses_inclusive_operator(self) -> None:
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            incremental_field="event_date",
            incremental_field_type=IncrementalFieldType.Date,
            incremental_last_value=datetime.date(2025, 1, 1),
        )
        assert "WHERE `event_date` >= %(incremental_value)s" in result.sql

    def test_order_by_can_be_suppressed(self) -> None:
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            incremental_last_value=datetime.datetime(2025, 1, 1),
            order_by_incremental=False,
        )
        assert "ORDER BY" not in result.sql


class TestParamStyles:
    def test_qmark_style_emits_question_mark(self) -> None:
        builder = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.QMARK)
        result = builder.select_all(
            schema="public",
            table_name="users",
            incremental_field="id",
            incremental_field_type=IncrementalFieldType.Integer,
            incremental_last_value=42,
        )
        assert 'WHERE "id" > ?' in result.sql
        assert result.params == [42]

    def test_named_style_uses_colon_prefix(self) -> None:
        builder = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.NAMED)
        result = builder.select_all(
            schema="public",
            table_name="users",
            incremental_field="id",
            incremental_field_type=IncrementalFieldType.Integer,
            incremental_last_value=42,
        )
        assert ":incremental_value" in result.sql
        assert result.params == {"incremental_value": 42}

    def test_numeric_style_uses_positional_number(self) -> None:
        builder = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.NUMERIC)
        result = builder.select_all(
            schema="public",
            table_name="users",
            incremental_field="id",
            incremental_field_type=IncrementalFieldType.Integer,
            incremental_last_value=42,
        )
        assert ":1" in result.sql
        assert result.params == [42]

    def test_empty_params_match_style(self) -> None:
        qmark = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.QMARK)
        named = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.PYFORMAT_NAMED)
        assert qmark.select_all(schema="public", table_name="t").params == []
        assert named.select_all(schema="public", table_name="t").params == {}
