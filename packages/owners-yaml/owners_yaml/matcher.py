"""GitHub-faithful CODEOWNERS pattern matcher.

Python port of ``.github/scripts/codeowners.js`` (itself a port of
hmarr/codeowners), reproducing GitHub's segment semantics: leading-slash root
anchoring, slash-free names behaving as ``**/`` prefixed, trailing-slash meaning
"this directory and everything under it", ``*`` never crossing ``/``, and a
literal final segment owning its whole subtree.

``[...]`` character classes are the one addition GitHub does not implement.
gitignore and fnmatch both have them, and ``schema.match_is_glob`` counts ``[``
as a glob character, so the matcher must read a class the same way.

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
    """Repo-relative, forward-slash path with any leading ``./`` or ``/`` and any trailing ``/``
    stripped. ``dir/`` and ``dir`` must resolve alike: with the slash kept, the walk would read the
    directory's own ownership file, and a new directory could opt out of its parent's additions."""
    p = file_path.replace("\\", SEP)
    while p.startswith("./"):
        p = p[2:]
    return p.strip(SEP)


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


def _class_char(ch: str) -> str:
    """One character as it must be spelled inside a regex ``[...]`` class."""
    return "\\" + ch if ch in "^]\\-" else ch


def _char_class(seg: str, start: int) -> tuple[str, int] | None:
    """Convert the ``[...]`` class opening at ``start`` into a regex class.

    Returns the regex plus the index just past the closing ``]``, or None when the
    class never closes. An unmatched ``[`` is then a literal, as in fnmatch. This is
    the one place where gitignore differs: its wildmatch makes such a pattern match
    nothing, which is the silent failure this matcher exists to prevent. ``/`` is
    dropped from the member list so no class can match across a segment boundary.
    """
    i = start + 1
    negated = i < len(seg) and seg[i] in "!^"
    if negated:
        i += 1
    body: list[str] = []
    first = True
    while i < len(seg):
        ch = seg[i]
        # A `]` in first position is a member, not the terminator.
        if ch == "]" and not first:
            if not body:
                # `[/]` has no members left: it can never match. `[!/]` keeps the
                # negation and becomes "any character but the separator".
                return ("[^/]" if negated else "(?!)"), i + 1
            inner = "".join(body)
            return (f"[^{inner}/]" if negated else f"[{inner}]"), i + 1
        first = False
        # A range needs both endpoints, so a `-` before the terminator is a member.
        if i + 2 < len(seg) and seg[i + 1] == "-" and seg[i + 2] != "]":
            body.append(f"{_class_char(ch)}-{_class_char(seg[i + 2])}")
            i += 3
            continue
        if ch != SEP:
            body.append(_class_char(ch))
        i += 1
    return None


def _seg_to_regex(seg: str) -> re.Pattern[str]:
    """Compile one pattern segment (may contain ``*``, ``?``, ``[...]`` classes and
    ``\\`` escapes) into an anchored regex matching exactly one path segment (never
    crossing ``/``)."""
    out = ["^"]
    i = 0
    while i < len(seg):
        ch = seg[i]
        if ch == "\\" and i + 1 < len(seg):
            out.append(re.escape(seg[i + 1]))
            i += 2
            continue
        if ch == "[":
            compiled = _char_class(seg, i)
            if compiled is not None:
                out.append(compiled[0])
                i = compiled[1]
                continue
            out.append(re.escape(ch))
        elif ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
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
        if not re.search(r"[*?\\\[]", pattern) and pattern.startswith(SEP):
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
