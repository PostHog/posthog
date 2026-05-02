"""Fixtures for hogql-no-string-table-chain rule.

Lines marked with the must-find annotation are expected to match the rule.
Lines marked as ok must not match. Run semgrep --test .semgrep/ locally.
"""

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EVENTS_TABLE_TYPES, EventsTable
from posthog.hogql.database.schema.persons import PersonsTable


# ============================================================================
# SHOULD FIND — production code comparing AST chains to table-name strings
# ============================================================================


def bad_events_check(node: ast.JoinExpr) -> bool:
    # ruleid: hogql-no-string-table-chain
    if isinstance(node.table, ast.Field) and node.table.chain == ["events"]:
        return True
    return False


def bad_persons_check(field: ast.Field) -> bool:
    # ruleid: hogql-no-string-table-chain
    return field.chain == ["persons"]


def bad_sessions_check(field: ast.Field) -> bool:
    # ruleid: hogql-no-string-table-chain
    return field.chain == ["sessions"]


def bad_groups_check(field: ast.Field) -> bool:
    # ruleid: hogql-no-string-table-chain
    return field.chain == ["groups"]


def bad_logs_check(field: ast.Field) -> bool:
    # ruleid: hogql-no-string-table-chain
    return field.chain == ["logs"]


def bad_qualified_check(field: ast.Field) -> bool:
    # ruleid: hogql-no-string-table-chain
    return field.chain == ["posthog", "events"]


def bad_ai_events_check(field: ast.Field) -> bool:
    # ruleid: hogql-no-string-table-chain
    return field.chain == ["posthog", "ai_events"]


def bad_reversed_operand(field: ast.Field) -> bool:
    # ruleid: hogql-no-string-table-chain
    return ["events"] == field.chain


# ============================================================================
# SHOULD NOT FIND — correct patterns and unrelated chain comparisons
# ============================================================================


def good_isinstance_check(context: HogQLContext, field: ast.Field) -> bool:
    # ok: hogql-no-string-table-chain
    if context.database is None:
        return False
    resolved = context.database.get_table([str(c) for c in field.chain])
    return isinstance(resolved, EventsTable)


def good_events_family_check(context: HogQLContext, field: ast.Field) -> bool:
    # ok: hogql-no-string-table-chain
    if context.database is None:
        return False
    resolved = context.database.get_table([str(c) for c in field.chain])
    return isinstance(resolved, EVENTS_TABLE_TYPES)


def good_persons_isinstance(context: HogQLContext, field: ast.Field) -> bool:
    # ok: hogql-no-string-table-chain
    resolved = context.database.get_table([str(c) for c in field.chain]) if context.database else None
    return isinstance(resolved, PersonsTable)


def good_column_name_check(field: ast.Field) -> bool:
    # Comparing a field chain to a COLUMN name (not a table name) is fine — these are
    # property lookups, not table-identity checks.
    # ok: hogql-no-string-table-chain
    if field.chain == ["timestamp"]:
        return True
    # ok: hogql-no-string-table-chain
    if field.chain == ["event"]:
        return True
    # ok: hogql-no-string-table-chain
    if field.chain == ["person_id"]:
        return True
    # ok: hogql-no-string-table-chain
    if field.chain == ["properties"]:
        return True
    return False


def good_multi_segment_property(field: ast.Field) -> bool:
    # ok: hogql-no-string-table-chain
    return field.chain == ["events", "person_id"]
