from typing import Any

import pytest
from posthog.test.base import BaseTest

from products.conversations.backend.models import Ticket
from products.conversations.backend.ticket_group_sql import (
    MAX_SQL_EXPRESSION_LENGTH,
    TicketGroupSqlError,
    build_ticket_group_sql_database,
    compile_ticket_group_sql,
)
from products.conversations.backend.ticket_groups import groups_use_sql


class TestCompileTicketGroupSql(BaseTest):
    """The HogQL → Postgres compiler behind the ticket_groups `sql` filter.

    Expressions come from team settings (hand-edited, or written over the API),
    so every rejection here is load-bearing: the printed fragment is spliced
    into the tickets-list CASE via RawSQL.
    """

    def setUp(self):
        super().setUp()
        self.database = build_ticket_group_sql_database(self.team, self.user)

    def compile(self, expression: str) -> tuple[str, list[Any]]:
        return compile_ticket_group_sql(expression, self.database, self.team.pk)

    def _ticket(self, **fields):
        """A real row, so the sample evaluation has something to evaluate."""
        fields.setdefault("channel_source", "widget")
        fields.setdefault("widget_session_id", "verify-session")
        fields.setdefault("distinct_id", "verify-user")
        return Ticket.objects.create_with_number(team=self.team, **fields)

    # --- accepted expressions -------------------------------------------------

    def test_compiles_a_simple_comparison_with_a_bound_parameter(self):
        sql, params = self.compile("status = 'open'")
        # Columns are qualified with the Django base-table alias so the fragment
        # can drop straight into a queryset on posthog_conversations_ticket.
        assert sql == "(posthog_conversations_ticket.status = %s)"
        assert params == ["open"]

    def test_binds_every_literal_and_keeps_parameter_order(self):
        sql, params = self.compile("status = 'open' AND priority = 'high'")
        assert "%(hogql_val" not in sql, "named placeholders must be rewritten for Django RawSQL"
        assert sql.count("%s") == 2
        assert params == ["open", "high"]

    def test_compiles_a_repeated_literal_positionally(self):
        # The same value twice must yield two positional params, in order.
        sql, params = self.compile("email_from = 'a@b.com' OR email_subject = 'a@b.com'")
        assert sql.count("%s") == len(params) == 2
        assert params == ["a@b.com", "a@b.com"]

    def test_compiles_numeric_comparison_without_parameters(self):
        sql, params = self.compile("message_count > 5")
        assert sql == "(posthog_conversations_ticket.message_count > 5)"
        assert params == []

    def test_compiles_is_null(self):
        sql, params = self.compile("sla_due_at IS NULL")
        assert sql == "(posthog_conversations_ticket.sla_due_at IS NULL)"
        assert params == []

    def test_compiles_in_list(self):
        sql, params = self.compile("status IN ('open', 'pending')")
        assert sql.count("%s") == 2
        assert params == ["open", "pending"]

    def test_compiles_case_insensitive_like(self):
        sql, params = self.compile("email_from ILIKE '%@bigcorp.com'")
        assert "ILIKE" in sql
        assert params == ["%@bigcorp.com"]

    def test_compiles_relative_date_arithmetic(self):
        sql, _params = self.compile("created_at > now() - toIntervalDay(7)")
        assert "NOW()" in sql
        assert "INTERVAL" in sql

    def test_compiles_json_traversal_by_chain(self):
        # Chain access is the working idiom for the JSON columns; it prints as
        # Postgres' native -> / ->> operators.
        sql, params = self.compile("session_context.plan = 'enterprise'")
        assert "session_context" in sql
        assert "enterprise" in params

    def test_rejects_clickhouse_json_functions(self):
        # JSONExtractString prints as json_extract_path_text, which in Postgres
        # takes `json` — session_context is `jsonb`, so it compiles but cannot
        # run. Caught by the executability check; use chain access instead.
        with pytest.raises(TicketGroupSqlError, match="Postgres rejected"):
            self.compile("JSONExtractString(session_context, 'plan') = 'enterprise'")

    def test_compiles_nested_boolean_logic(self):
        sql, _params = self.compile("status = 'open' AND (message_count > 5 OR unread_team_count > 0)")
        assert "AND" in sql and "OR" in sql

    # --- rejections ----------------------------------------------------------

    def test_rejects_a_non_boolean_expression(self):
        # Postgres arbitrates this (see the note where the static type check used
        # to be), so assert on the behaviour rather than our own wording.
        for expression in ("1", "'hello'", "message_count", "email_from"):
            with pytest.raises(TicketGroupSqlError, match="Postgres rejected"):
                self.compile(expression)

    def test_accepts_boolean_expressions_hogql_types_loosely(self):
        # These are real conditions that HogQL does NOT type as ast.BooleanType;
        # they must still be accepted, which is why there's no static type gate.
        for expression in (
            "if(message_count > 5, true, false)",
            "multiIf(message_count > 10, true, false)",
            "startsWith(email_from, 'vip')",
            "empty(email_from)",
        ):
            sql, _params = self.compile(expression)
            assert sql

    def test_rejects_aggregations(self):
        with pytest.raises(TicketGroupSqlError, match="[Aa]ggregate"):
            self.compile("count() > 1")

    def test_rejects_window_functions(self):
        with pytest.raises(TicketGroupSqlError, match="[Ww]indow"):
            self.compile("row_number() OVER () = 1")

    def test_rejects_subqueries(self):
        # Critical: a subquery on system.support_tickets prints as a ClickHouse
        # postgresql() table function whose bound params include this
        # deployment's database password.
        with pytest.raises(TicketGroupSqlError, match="[Ss]ubquer"):
            self.compile("id IN (SELECT id FROM system.support_tickets)")

    def test_rejects_unknown_columns(self):
        with pytest.raises(TicketGroupSqlError, match="nope_col"):
            self.compile("nope_col = 1")

    def test_rejects_tags_with_guidance_towards_the_tags_filter(self):
        # tags are a relational lazy join; they cannot compile in an
        # expression, and the ticket_tags filter is the right tool.
        for expression in ("tags = 'vip'", "has(tags.names, 'vip')"):
            with pytest.raises(TicketGroupSqlError) as caught:
                self.compile(expression)
            assert "tag" in str(caught.value).lower()

    def test_rejects_syntax_errors(self):
        with pytest.raises(TicketGroupSqlError):
            self.compile("status = ")

    def test_rejects_sql_injection_attempts_at_the_parser(self):
        with pytest.raises(TicketGroupSqlError):
            self.compile("status = 'x'); DROP TABLE posthog_conversations_ticket; --'")

    def test_rejects_functions_outside_the_postgres_allowlist(self):
        with pytest.raises(TicketGroupSqlError):
            self.compile("sleep(10) = 1")

    def test_rejects_an_empty_expression(self):
        for expression in ("", "   "):
            with pytest.raises(TicketGroupSqlError, match="empty"):
                self.compile(expression)

    def test_rejects_an_over_long_expression(self):
        with pytest.raises(TicketGroupSqlError, match="too long"):
            self.compile("status = 'open' OR " * 200 + "status = 'x'")

    def test_rejects_set_returning_functions(self):
        # These compile cleanly and are typed boolean, but Postgres refuses them
        # inside a CASE/WHEN ("argument of CASE/WHEN must not return a set"), so
        # without the executability check they'd store fine and then 500 every
        # tickets list for the team.
        for expression in ("generateSeries(1, 10) > 0", "arrayJoin([1, 2, 3]) > 0"):
            with pytest.raises(TicketGroupSqlError):
                self.compile(expression)

    def test_rejects_row_dependent_allocation_bombs(self):
        # The dangerous cousin of the constant-folding bomb: because `email_from`
        # is a COLUMN, the planner can't fold this, so it plans instantly and then
        # allocates ~100MB per row when the tickets list runs. Only evaluating
        # against real rows catches it — which is why validation executes over a
        # sample rather than just EXPLAINing.
        self._ticket(email_from="someone@example.com")
        with pytest.raises(TicketGroupSqlError, match="too expensive"):
            self.compile("repeat(email_from, 100000000) = 'x'")

    def test_rejects_expressions_that_only_fail_on_real_rows(self):
        # Division by zero can't be seen without rows either.
        self._ticket(email_from="someone@example.com")
        with pytest.raises(TicketGroupSqlError, match="Postgres rejected"):
            self.compile("(1 / (message_count - message_count)) > 0")

    def test_accepts_a_sane_expression_against_real_rows(self):
        # The sample evaluation must not reject legitimate expressions.
        self._ticket(email_from="vip@bigcorp.com", message_count=7)
        sql, params = self.compile("message_count > 3 AND email_from ILIKE '%@bigcorp.com'")
        assert sql and params == ["%@bigcorp.com"]

    def test_rejects_expressions_too_expensive_to_even_plan(self):
        # Postgres constant-folds immutable functions during planning, so this
        # 28-character expression really does allocate ~400MB server-side — the
        # length cap is no protection. The statement_timeout is.
        with pytest.raises(TicketGroupSqlError, match="too expensive"):
            self.compile("repeat('a', 400000000) = 'x'")

    def test_never_emits_sensitive_parameters(self):
        # Belt and braces on top of the subquery rejection: nothing we accept
        # may carry the *_sensitive connection params the postgres() printer binds.
        sql, params = self.compile("status = 'open'")
        assert "sensitive" not in sql
        assert all(not isinstance(param, str) or "password" not in param for param in params)


class TestGroupsUseSql(BaseTest):
    """The gate that decides whether to build the (expensive) HogQL database.
    It runs on UNVALIDATED input on the write path, so malformed shapes must
    return False rather than raise — otherwise a bad write 500s instead of 400s.
    """

    def test_detects_a_sql_filter(self):
        assert groups_use_sql([{"label": "A", "filters": [{"type": "sql", "expression": "status = 'open'"}]}])

    def test_false_without_a_sql_filter(self):
        assert not groups_use_sql(
            [{"label": "A", "filters": [{"type": "ticket_tags", "operator": "any_of", "value": []}]}]
        )
        assert not groups_use_sql([{"label": "A", "filters": []}])
        assert not groups_use_sql([])

    def test_tolerates_malformed_input_without_raising(self):
        # `filters` of a non-iterable type used to raise TypeError here, turning
        # a 400 into a 500. A string is iterable, so it needs covering too.
        for groups in (
            None,
            "nope",
            [None],
            ["nope"],
            [{"label": "A"}],
            [{"label": "A", "filters": 5}],
            [{"label": "A", "filters": True}],
            [{"label": "A", "filters": "vip"}],
            [{"label": "A", "filters": {"type": "sql"}}],
            [{"label": "A", "filters": [None]}],
        ):
            assert groups_use_sql(groups) is False, groups


class TestTicketGroupSqlLengthCap(BaseTest):
    """The cap is enforced on the raw expression, not the printed SQL."""

    def setUp(self):
        super().setUp()
        self.database = build_ticket_group_sql_database(self.team, self.user)

    def _expression_of_length(self, length: int) -> str:
        # `status = 'aaa…'` padded to exactly `length` characters.
        prefix = "status = '"
        return prefix + "a" * (length - len(prefix) - 1) + "'"

    def test_accepts_an_expression_at_the_cap(self):
        expression = self._expression_of_length(MAX_SQL_EXPRESSION_LENGTH)
        assert len(expression) == MAX_SQL_EXPRESSION_LENGTH
        sql, params = compile_ticket_group_sql(expression, self.database, self.team.pk)
        assert sql and len(params) == 1

    def test_rejects_one_character_over_the_cap(self):
        expression = self._expression_of_length(MAX_SQL_EXPRESSION_LENGTH + 1)
        with pytest.raises(TicketGroupSqlError, match="too long"):
            compile_ticket_group_sql(expression, self.database, self.team.pk)
