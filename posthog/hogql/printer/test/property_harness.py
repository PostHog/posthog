"""Shared compile/normalize helpers for the property characterization net.

Both the golden harness (``test_property_golden.py``) and the reachability oracle compile corpus cases the same way:
parse the HogQL, build a per-dialect context, run the full ``prepare_ast_for_printing`` pipeline, print. Factoring it
here keeps the two consumers from drifting (and keeps a single place to evolve when the pipeline changes).
"""

from __future__ import annotations

import re

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models import Team

# Placeholder the golden uses in place of the (per-run, auto-increment) team primary key, so golden text is stable.
TEAM_PLACEHOLDER = "<TEAM>"


def compile_case(
    sql: str,
    dialect: HogQLDialect,
    team: Team,
    modifiers: HogQLQueryModifiers | None = None,
) -> tuple[str, ast.Expr | None]:
    """Run the full prepare-and-print pipeline for one corpus case and dialect.

    Returns ``(printed_sql, prepared_ast)``. The prepared AST is the post-pipeline tree (what the printer saw), exposed
    so callers — the oracle in particular — can assert structural facts about it, not just the rendered string.
    """
    node = parse_select(sql)
    context = HogQLContext(
        team_id=team.pk,
        team=team,
        enable_select_queries=True,
        modifiers=modifiers or create_default_modifiers_for_team(team),
    )
    printed, prepared = prepare_and_print_ast(node, context, dialect=dialect)
    return printed, prepared


def normalize(sql: str, team: Team) -> str:
    """Replace the team-id guard literal with a stable placeholder so golden text doesn't churn per run.

    Only the ``team_id, <pk>`` guard is replaced (the trailing ``\\b`` keeps ``team_id, 1`` from matching
    ``team_id, 10``); array indices, ``ifNull(..., 1)`` defaults, and other literals that happen to equal the pk are
    left untouched.
    """
    return re.sub(rf"team_id, {team.pk}\b", f"team_id, {TEAM_PLACEHOLDER}", sql)
