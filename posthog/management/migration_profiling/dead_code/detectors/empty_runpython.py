"""Detector F — RunPython operations whose forward body does nothing.

Recognises three flavours:

1. ``migrations.RunPython(migrations.RunPython.noop)`` — explicit no-op
   sentinel.
2. ``def forward(apps, schema_editor): pass`` — body is literally ``pass``.
3. ``def forward(apps, schema_editor): return`` / ``return None`` — same
   thing in different shape.

A leading docstring is stripped before the body check, so a documented
no-op still counts as empty.

These are pure-AST dead code: they pay the migration overhead but produce
zero schema or data effect. Confidence is ``HIGH`` because there's no path
that makes a literal ``pass`` not be a no-op.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

from posthog.management.migration_profiling.dead_code.detector_base import AnalysisContext, Detector
from posthog.management.migration_profiling.dead_code.models import Finding


class EmptyRunPythonDetector(Detector):
    name = "empty_runpython"
    description = "RunPython ops whose forward callable does nothing observable."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        for migration in ctx.migrations:
            for idx, op in enumerate(migration.operations):
                if op.class_name != "RunPython":
                    continue
                if op.runpython_is_explicit_noop:
                    yield self._build_finding(migration.app, migration.name, idx, op, "explicit_noop")
                    continue
                body = op.runpython_callable_body_source
                if body is None:
                    continue
                if _body_is_effectively_empty(body):
                    yield self._build_finding(migration.app, migration.name, idx, op, "empty_body")

    def _build_finding(self, app: str, name: str, op_index: int, op, kind: str) -> Finding:
        callable_name = op.runpython_callable_name or "<unknown>"
        summary = (
            f"RunPython in {app}.{name} is a no-op "
            f"({'noop sentinel' if kind == 'explicit_noop' else f'callable `{callable_name}` body is empty'})"
        )
        detail_lines = [
            f"App: {app}",
            f"Migration: {name}",
            f"Operation index: {op_index}",
            f"Callable: {callable_name}",
            f"Detection: {kind}",
        ]
        if op.runpython_callable_body_source:
            detail_lines.append("Body:")
            detail_lines.append(op.runpython_callable_body_source)
        return Finding(
            detector_name=self.name,
            kind=kind,
            summary=summary,
            confidence=1.0,
            migrations=[(app, name)],
            detail="\n".join(detail_lines),
            metadata={
                "app": app,
                "migration": name,
                "callable": callable_name,
                "detection_kind": kind,
            },
        )


def _body_is_effectively_empty(body_source: str) -> bool:
    """Return True if a function body — given as the source of its statements —
    has no observable effect."""
    try:
        # ``ast.parse(... , mode="exec")`` over multiple top-level statements.
        tree = ast.parse(body_source)
    except SyntaxError:
        return False
    stmts = list(tree.body)
    # Strip a leading docstring if present.
    if (
        stmts
        and isinstance(stmts[0], ast.Expr)
        and isinstance(stmts[0].value, ast.Constant)
        and isinstance(stmts[0].value.value, str)
    ):
        stmts = stmts[1:]
    if not stmts:
        return True
    if len(stmts) > 1:
        return False
    only = stmts[0]
    if isinstance(only, ast.Pass):
        return True
    if isinstance(only, ast.Return):
        value = only.value
        if value is None:
            return True
        if isinstance(value, ast.Constant) and value.value is None:
            return True
    return False
