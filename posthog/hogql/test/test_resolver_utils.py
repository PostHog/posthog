from __future__ import annotations

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.resolver import resolve_table_scope
from posthog.hogql.resolver_utils import field_resolution_hint


def _hint(table: list[str], name: str, **kwargs) -> str:
    context = HogQLContext(team_id=None, database=Database(), enable_select_queries=True)
    scope = resolve_table_scope(table, context, "hogql")
    return field_resolution_hint(scope, name, context, **kwargs)


def test_lists_columns_when_nothing_is_close() -> None:
    # is_sample is returned by the insights REST API but is not a HogQL column, and it is too far
    # from any real column to fuzzy-match. Without the list this is a bare error, and recovering
    # from it costs a second schema-discovery query.
    hint = _hint(["system", "insights"], "is_sample")

    assert hint.startswith(". Available fields: ")
    assert "short_id" in hint
    assert "saved" in hint


def test_omits_hidden_fields() -> None:
    # `saved` is an expression column over the hidden `_saved`; only the alias is usable.
    assert "_saved" not in _hint(["system", "insights"], "is_sample")


def test_prefers_a_close_match_over_the_full_list() -> None:
    hint = _hint(["system", "insights"], "created_by")

    assert hint.startswith(". Did you mean: ")
    assert "created_by_id" in hint
    assert "Available fields" not in hint


def test_caps_the_list_on_a_wide_table() -> None:
    hint = _hint(["events"], "definitely_not_a_column")

    assert hint.startswith(". Available fields include: ")
    assert hint.endswith(", …")
    listed = hint.removeprefix(". Available fields include: ").removesuffix(", …")
    assert len(listed.split(", ")) == 25


def test_silent_for_a_table_qualifier() -> None:
    # A failed first link of a longer chain is a scoping problem, so a column list only distracts.
    assert _hint(["system", "insights"], "is_sample", bare_reference=False) == ""
