"""Shared helpers for the HogQL parser-parity diagnostic scripts.

Imported by `pbt_diagnostic.py`, `pbt_corpus.py`, `parser_bench.py`,
and `log_corpus_diagnostic.py` in this directory. Not a CLI itself —
the leading underscore marks it as a private helper module.

Holds the cross-script vocabulary:

- **AST diff path** — `_node_type` / `_diff_path` / `_format_diff_path`
  walk two ASTs together and pinpoint the first divergence.
- **Divergence shape** — `DivergenceShape` / `_ast_mismatch_shape` /
  `_shape_for` reduce a divergence to a structural key two examples of
  the same bug compare equal under.
- **Error normalisation** — `_normalize_error` / `_reject_error` strip
  position-dependent payloads so same-cause rejects bucket together.
- **Backend probe** — `_probe_backend` fails fast on an unusable
  `--oracle` / `--candidate`.

Importing this module pulls `posthog.hogql.*` — callers must have run
`django.setup()` first (every script here does, before its imports).
"""

from __future__ import annotations

import re
import dataclasses
from typing import Any

from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.test.test_parser_grammar_pbt import _try_parse

# ---------------------------------------------------------------------------
# AST diff path
# ---------------------------------------------------------------------------


def _node_type(node: Any) -> str:
    """Top-level AST node type label, e.g. `Call` / `ExprCall` / `Not`."""
    return type(node).__name__ if node is not None else "<None>"


def _node_fields(node: Any) -> list[tuple[str, Any]]:
    """`(field_name, value)` pairs for an AST node in declaration order.
    HogQL AST nodes are `__slots__` dataclasses, so `dataclasses.fields()`
    is the canonical accessor; non-dataclass leaves return `[]` and fall
    through to the value-terminal branch in `_diff_path`."""
    if not dataclasses.is_dataclass(node):
        return []
    return [(f.name, getattr(node, f.name, None)) for f in dataclasses.fields(node)]


def _diff_path(oracle: Any, candidate: Any, path: list | None = None, depth: int = 0) -> list:
    """Walk both ASTs together; return the `.field` / `[i]` breadcrumbs
    from root to the first divergence, terminating with a 3-tuple
    `(label, oracle_repr, candidate_repr)`. Depth-bounded so pathological
    deep trees don't blow the stack."""
    path = path or []
    if depth > 64:
        return [*path, ("<depth-limit>", repr(oracle)[:120], repr(candidate)[:120])]
    if oracle == candidate:
        return path
    o_t = _node_type(oracle)
    c_t = _node_type(candidate)
    if o_t != c_t:
        return [*path, ("<type>", o_t, c_t)]

    if isinstance(oracle, list) and isinstance(candidate, list):
        if len(oracle) != len(candidate):
            return [*path, ("<len>", str(len(oracle)), str(len(candidate)))]
        for i, (a, b) in enumerate(zip(oracle, candidate)):
            if a != b:
                return _diff_path(a, b, [*path, f"[{i}]"], depth + 1)
        return path
    if isinstance(oracle, dict) and isinstance(candidate, dict):
        if set(oracle) != set(candidate):
            return [*path, ("<keys>", str(sorted(oracle)), str(sorted(candidate)))]
        for k in oracle:
            if oracle[k] != candidate[k]:
                return _diff_path(oracle[k], candidate[k], [*path, f"[{k!r}]"], depth + 1)
        return path
    o_fields = _node_fields(oracle)
    c_fields = dict(_node_fields(candidate))
    if o_fields:
        for name, ov in o_fields:
            cv = c_fields.get(name)
            if ov == cv:
                continue
            return _diff_path(ov, cv, [*path, f".{name}"], depth + 1)
        return [*path, ("<unequal-but-fields-match>", repr(oracle)[:120], repr(candidate)[:120])]
    return [*path, ("<value>", repr(oracle), repr(candidate))]


def _format_diff_path(steps: list) -> str:
    """Format a diff path as breadcrumbs ending with the differing
    oracle/candidate values."""
    if not steps:
        return "  (no diff)"
    breadcrumbs: list[str] = []
    terminal: tuple[str, str, str] | None = None
    for step in steps:
        if isinstance(step, tuple):
            terminal = step
        else:
            breadcrumbs.append(step)
    label = "root" + "".join(breadcrumbs)
    if terminal is None:
        return f"  {label}: (no terminal value)"
    field, o_repr, c_repr = terminal
    return f"  {label}{field}\n    oracle:    {o_repr[:200]}\n    candidate: {c_repr[:200]}"


# ---------------------------------------------------------------------------
# Divergence shape (a stable bucket key — used for shrinking + corpus dedup)
# ---------------------------------------------------------------------------
#
# Two divergences are "the same shape" if they reach the same terminal
# diff at the same root-type pair, OR they're the same kind of reject
# (matching error message).


@dataclasses.dataclass(frozen=True)
class DivergenceShape:
    """Structural-only divergence descriptor — designed so two examples
    of the same divergence (with different leaf values) compare equal.

    For ast_mismatch:
      - `kind` = "ast_mismatch"
      - `root_pair` = (oracle_root_type, candidate_root_type)
      - `terminal_kind` = the kind tag of the final diff step
        (`<type>` / `<value>` / `<keys>` / `<len>` /
        `<unequal-but-fields-match>` / `<depth-limit>`).
      - `terminal_types` = for `<type>` terminals only, the
        (oracle_type, candidate_type) pair that diverged. None for
        all other terminal kinds — those are inherently structural.

    For candidate_reject:
      - `kind` = "candidate_reject"
      - `reject_signature` = the normalised error message
    """

    kind: str
    root_pair: tuple[str, str] | None = None
    terminal_kind: str | None = None
    terminal_types: tuple[str, str] | None = None
    reject_signature: str | None = None


def _ast_mismatch_shape(root_pair: tuple[str, str], steps: list) -> DivergenceShape:
    """Build a structural `DivergenceShape` for an ast_mismatch from the
    root-type pair and the diff-path output. Accepts both tuple-form
    steps (in-memory) and list-form (after JSON round-trip). Leaf VALUES
    of `<value>` / `<keys>` / `<len>` are intentionally dropped — two
    divergences are "the same shape" if they reach the same kind of leaf
    at the same root, regardless of which specific value differed."""
    terminal: tuple[str, str, str] | None = None
    for s in reversed(steps):
        if isinstance(s, tuple) and len(s) == 3:
            terminal = s
            break
        if isinstance(s, list) and len(s) == 3 and all(isinstance(x, str) for x in s):
            terminal = (s[0], s[1], s[2])
            break
    if terminal is None:
        return DivergenceShape(kind="ast_mismatch", root_pair=root_pair)
    kind_tag = terminal[0]
    types = (terminal[1], terminal[2]) if kind_tag == "<type>" else None
    return DivergenceShape(
        kind="ast_mismatch",
        root_pair=root_pair,
        terminal_kind=kind_tag,
        terminal_types=types,
    )


# ---------------------------------------------------------------------------
# Error normalisation
# ---------------------------------------------------------------------------

_GOT_RE = re.compile(r"got\s+\S+", re.IGNORECASE)


def _normalize_error(msg: str) -> str:
    """Strip position-dependent suffixes so similar rejects bucket
    together — e.g. `expected ), got Keyword(Order)` and `expected ),
    got Number` collapse to `expected ), got <X>`."""
    return _GOT_RE.sub("got <X>", msg)[:120]


def _reject_error(query: str, rule: str, backend: str) -> str:
    """Capture the candidate's reject error message, normalised. Only
    called for queries `_try_parse` already returned `False` for — but
    `_try_parse` swallows EVERY `Exception` subclass, not just
    `BaseHogQLError`, so a backend-internal crash (`RuntimeError`,
    `TypeError`, …) also reaches here. We normalise those into a
    distinct `<ExcType>: …` signature rather than letting them
    propagate."""
    parser_fn = parse_expr if rule == "expr" else parse_select
    try:
        parser_fn(query, backend=backend)  # type: ignore[arg-type]
    except BaseHogQLError as e:
        return _normalize_error(str(e))
    except Exception as e:
        return _normalize_error(f"{type(e).__name__}: {e}")
    return "(unexpected: parse succeeded)"


# ---------------------------------------------------------------------------
# Backend probe + divergence classifier
# ---------------------------------------------------------------------------


def _probe_backend(rule: str, backend: str) -> str | None:
    """Sanity-probe a backend by parsing `"1"` directly through the
    parser entry point. Returns None on success, or a human-readable
    error message. Bypasses `_try_parse` deliberately — `_try_parse`
    swallows `BaseHogQLError` (legitimate rejections) AND would let an
    invalid backend name raising `KeyError` through silently."""
    probe_fn = parse_expr if rule == "expr" else parse_select
    try:
        probe_fn("1", backend=backend)  # type: ignore[arg-type]
    except BaseHogQLError:
        # Rejecting `"1"` would be surprising but isn't a backend
        # failure — `_try_parse` would also classify this as a reject.
        return None
    except Exception as e:
        return str(e)
    return None


def _shape_for(
    query: str,
    rule: str,
    oracle_backend: str,
    candidate_backend: str,
) -> DivergenceShape | None:
    """Determine the divergence shape of `query`, or None if there's no
    divergence between oracle and candidate."""
    o_ok, o_ast = _try_parse(query, rule, oracle_backend)
    if not o_ok:
        return None  # oracle reject — not a divergence we care about
    c_ok, c_ast = _try_parse(query, rule, candidate_backend)
    if not c_ok:
        return DivergenceShape(
            kind="candidate_reject",
            reject_signature=_reject_error(query, rule, candidate_backend),
        )
    if o_ast == c_ast:
        return None
    return _ast_mismatch_shape((_node_type(o_ast), _node_type(c_ast)), _diff_path(o_ast, c_ast))
