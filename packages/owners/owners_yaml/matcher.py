"""GitHub-faithful CODEOWNERS pattern matcher.

Python port of ``.github/scripts/codeowners.js`` (itself a port of
hmarr/codeowners), reproducing GitHub's segment semantics: leading-slash root
anchoring, slash-free names behaving as ``**/`` prefixed, trailing-slash meaning
"this directory and everything under it", ``*`` never crossing ``/``, and a
literal final segment owning its whole subtree.

Used both for ``owners.yaml`` ``rules:`` globs and by the legacy differ to
replicate the assigner's ``CODEOWNERS-soft`` behavior, so it must stay faithful.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache
from typing import Literal

SEP = "/"


def normalize_path(file_path: str) -> str:
    """Repo-relative, forward-slash path with any leading ``./`` or ``/`` stripped."""
    p = file_path.replace("\\", SEP)
    while p.startswith("./"):
        p = p[2:]
    while p.startswith(SEP):
        p = p[1:]
    return p


def pattern_to_segments(pattern: str) -> list[str]:
    """Normalize a pattern into GitHub-semantics path segments.

    Applies the leading-slash (root-anchor), slash-free (``**`` prefix), and
    trailing-slash (``**`` suffix) rules, then collapses consecutive ``**``.
    Raises ``ValueError`` on the patterns GitHub rejects. ``/`` is handled by
    callers and never passed here.
    """
    if "***" in pattern:
        raise ValueError("pattern cannot contain three consecutive asterisks")
    if pattern == "":
        raise ValueError("empty pattern")

    segs = pattern.split(SEP)

    if segs[0] == "":
        # Leading slash anchors to the repo root: drop the empty first segment.
        segs = segs[1:]
    elif len(segs) == 1 or (len(segs) == 2 and segs[1] == ""):
        # A slash-free name (`foo`, `foo/`, `*.js`) matches at any depth, so it
        # behaves as if prefixed with `**/`.
        if segs[0] != "**":
            segs = ["**", *segs]

    if len(segs) > 1 and segs[-1] == "":
        # A trailing slash means "this directory and everything under it".
        segs[-1] = "**"

    # Collapse runs of consecutive `**` into one — semantically identical, and two
    # adjacent `**` would otherwise compile to a degenerate, never-matching form.
    collapsed: list[str] = []
    for seg in segs:
        if seg == "**" and collapsed and collapsed[-1] == "**":
            continue
        collapsed.append(seg)
    return collapsed


def _seg_to_regex(seg: str) -> re.Pattern[str]:
    """Compile one literal segment (may contain ``*``, ``?``, ``\\`` escapes) into
    an anchored regex matching exactly one path segment (never crossing ``/``)."""
    out = ["^"]
    escape = False
    for ch in seg:
        if escape:
            escape = False
            out.append(re.escape(ch))
        elif ch == "\\":
            escape = True
        elif ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
    out.append("$")
    return re.compile("".join(out))


class _Token:
    """One compiled pattern token: ``**`` (star), ``*`` (one), or a literal."""

    __slots__ = ("type", "test")

    def __init__(self, type_: Literal["star", "one", "lit"], test: Callable[[str], bool]) -> None:
        self.type = type_
        self.test = test


def _glob_match(tokens: list[_Token], path_segs: list[str]) -> bool:
    """Match tokenized pattern against path segments with no cross-segment
    backtracking: a bottom-up ``dp[ti][pi]`` scan, O(tokens x segments).

    Encodes the same rules as the JS reference: ``**`` matches zero or more whole
    segments (a trailing ``**`` needs at least one), ``*`` and literals each match
    exactly one segment, and a literal final segment also owns its subtree.
    """
    m = len(tokens)
    n = len(path_segs)
    # nxt holds dp[ti + 1][*]; seed with dp[m][pi] = (no tokens left → path exhausted).
    nxt = [pi == n for pi in range(n + 1)]
    for ti in range(m - 1, -1, -1):
        tok = tokens[ti]
        is_last = ti == m - 1
        cur = [False] * (n + 1)
        if tok.type == "star":
            if is_last:
                # A trailing `**` consumes every remaining segment but needs one.
                for pi in range(n + 1):
                    cur[pi] = (n - pi) >= 1
            else:
                cur[n] = nxt[n]
                for pi in range(n - 1, -1, -1):
                    cur[pi] = nxt[pi] or cur[pi + 1]
        else:
            for pi in range(n):
                if not tok.test(path_segs[pi]):
                    continue
                cur[pi] = True if (is_last and tok.type == "lit") else nxt[pi + 1]
        nxt = cur
    return nxt[0]


class PatternMatcher:
    """A single compiled CODEOWNERS pattern. ``test(path)`` returns whether a
    normalized repo-relative path is matched."""

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self._literal_prefix: str | None = None
        self._tokens: list[_Token] | None = None

        # Fast path for left-anchored patterns with no wildcards (the common case).
        if not re.search(r"[*?\\]", pattern) and pattern.startswith(SEP):
            self._literal_prefix = pattern[1:]
            return

        self._tokens = []
        for seg in pattern_to_segments(pattern):
            if seg == "**":
                self._tokens.append(_Token("star", lambda _s: False))
            elif seg == "*":
                self._tokens.append(_Token("one", lambda s: len(s) >= 1))
            else:
                regex = _seg_to_regex(seg)
                self._tokens.append(_Token("lit", lambda s, r=regex: bool(r.match(s))))

    def test(self, path: str) -> bool:
        prefix = self._literal_prefix
        if prefix is not None:
            if prefix == "":
                return False
            if prefix.endswith(SEP):
                return path.startswith(prefix)
            if len(path) == len(prefix):
                return path == prefix
            if len(path) > len(prefix) and path[len(prefix)] == SEP:
                return path[: len(prefix)] == prefix
            return False

        assert self._tokens is not None
        return _glob_match(self._tokens, path.split(SEP) if path else [])


@lru_cache(maxsize=4096)
def compile_pattern(pattern: str) -> PatternMatcher:
    """Compile a pattern (cached), raising ``ValueError`` on the invalid ones GitHub rejects."""
    return PatternMatcher(pattern)


def path_matches_pattern(pattern: str, file_path: str) -> bool:
    """Whether a single CODEOWNERS pattern matches a repo-relative path."""
    return compile_pattern(pattern).test(normalize_path(file_path))
