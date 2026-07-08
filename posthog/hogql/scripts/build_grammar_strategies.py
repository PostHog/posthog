#!/usr/bin/env python3
"""Regenerate the HogQL grammar PBT strategies module.

Reads ``posthog/hogql/grammar/HogQLParser.g4`` and
``posthog/hogql/grammar/HogQLLexer.common.g4`` and emits
``posthog/hogql/test/_generated_grammar_strategies.py``.

The output is a Python module of Hypothesis strategies — one per
parser rule — that produce syntactically valid HogQL strings. It's
consumed by ``test_parser_grammar_pbt.py`` to drive differential
parsing against the Python and C++ HogQL parsers.

Variable-content tokens (``IDENTIFIER``, ``STRING_LITERAL``, etc.)
are hand-written once in
``posthog/hogql/test/_grammar_token_strategies.py`` and referenced by
name from the emitted module — that's the only piece that needs
human attention when the grammar gains a new variable-content token.

Modes:

    python -m posthog.hogql.scripts.build_grammar_strategies
        Regenerate and write the file.

    python -m posthog.hogql.scripts.build_grammar_strategies --check
        Regenerate to memory and exit non-zero if the on-disk file
        differs. Use in CI to catch drift between the grammar and the
        checked-in generated strategies.

Pipeline:

    1. Lex the .g4 source into a stream of tokens (g4_lex)
    2. Parse it into a Grammar AST: list of named rules, each with
       alternatives, each alternative a sequence of Elements (g4_parse)
    3. Resolve token names (``SELECT``) to their literal text (``"SELECT"``)
       via the lexer grammar (resolve_tokens)
    4. Drop rules and alternatives that reference excluded regions —
       HogQLX, Hog programs, template strings (apply_exclusions)
    5. Detect left-recursive rules and rewrite them into a Pratt-shaped
       seed-plus-suffix form (rewrite_left_recursion)
    6. Emit a Python module string with one ``@st.composite`` function
       per rule (emit)
"""
# ruff: noqa: T201

from __future__ import annotations

import re
import sys
import argparse
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# AST types for parsed grammar
# ---------------------------------------------------------------------------

ElementKind = Literal["token", "rule", "literal", "group"]
Quantifier = Literal["", "?", "*", "+"]


@dataclass
class Element:
    """One element in an alternative sequence.

    ``token``  — uppercase token reference (``SELECT``); resolved to text
    ``rule``   — lowercase rule reference (``columnExpr``); recursed into
    ``literal`` — single-quoted literal in the .g4 source (``'foo'``); rare
    ``group``  — ``(...)`` group; ``children`` holds nested alternatives
    """

    kind: ElementKind
    name: str = ""  # token or rule name
    text: str = ""  # literal text (for kind == 'literal')
    children: list[Alternative] = field(default_factory=list)  # for groups
    quantifier: Quantifier = ""


@dataclass
class Alternative:
    """One ``|``-separated alternative inside a rule."""

    elements: list[Element] = field(default_factory=list)
    # ``# AltName`` suffix in the .g4 file (we preserve for diagnostics
    # but don't use semantically).
    alt_name: str | None = None


@dataclass
class Rule:
    """A grammar rule."""

    name: str
    alternatives: list[Alternative] = field(default_factory=list)


@dataclass
class Grammar:
    """The entire parsed grammar."""

    rules: dict[str, Rule] = field(default_factory=dict)
    # Insertion order matters for alternative priority — preserve via list
    rule_order: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# .g4 lexer
# ---------------------------------------------------------------------------
#
# Tokenises a .g4 source into a small set of token kinds. ANTLR grammar
# syntax we care about (and what we ignore):
#
#   IDENT         lowercase identifier — parser-rule name or rule reference
#   TOKEN         uppercase identifier — token name or token reference
#   STRING        single-quoted literal (``'foo'``, ``'\\\\'``)
#   PUNCT         one of ``: ; | ( ) ? * + = #``
#   ASSOC         ``<assoc=right>`` annotation (we skip)
#
#   Skipped: ``//`` and ``/* */`` comments, whitespace, ``options { ... }``
#   block, ``grammar`` / ``parser`` / ``lexer`` headers, ``mode`` directives.

_G4_TOKEN_RE = re.compile(
    r"""
    (?P<comment_line>  //[^\n]*                          )|
    (?P<comment_block> /\*.*?\*/                         )|  # non-greedy
    (?P<string>        ' (?: \\. | [^'\\] )* '           )|
    (?P<charclass>     \[ (?: \\. | [^\]\\] )* \]        )|  # lexer-only [a-z], [aA], etc.
    (?P<assoc>         <[^>]*>                           )|
    (?P<action>        \{ (?: [^{}'] | '(?:\\.|[^'])*'   )*?  \} \??  )|
    (?P<arrow>         ->                                )|
    (?P<ident>         [A-Za-z_][A-Za-z0-9_]*            )|
    (?P<punct>         [:;|()?*+=#,]                     )|
    (?P<dot>           \.                                )|
    (?P<tilde>         ~                                 )|
    (?P<ws>            \s+                               )
    """,
    re.VERBOSE | re.DOTALL,
)


@dataclass
class G4Token:
    kind: str
    text: str
    pos: int  # for error messages


def g4_lex(src: str) -> list[G4Token]:
    """Tokenise a .g4 source. Skips comments, whitespace, and
    parser/lexer/mode header lines."""
    out: list[G4Token] = []
    i = 0
    n = len(src)
    while i < n:
        m = _G4_TOKEN_RE.match(src, i)
        if not m:
            raise ValueError(f"Unexpected character at {i}: {src[i : i + 20]!r}")
        kind = m.lastgroup
        assert kind is not None
        text = m.group(0)
        i = m.end()
        if kind in ("comment_line", "comment_block", "ws", "assoc", "action"):
            continue
        if kind == "charclass":
            # Lexer-only character class (``[a-z]``, ``[aA]``). We never
            # need to render its content as a literal — any lexer rule
            # that uses one has variable content and is escape-hatched.
            # Emit a sentinel kind the parser can ignore as an opaque
            # element.
            out.append(G4Token("charclass", text, m.start()))
            continue
        if kind == "ident":
            # The ``parser grammar X;`` / ``lexer grammar X;`` / ``mode X;``
            # headers slip through as ident sequences. We strip them at
            # the parser level rather than the lexer level for clarity.
            out.append(G4Token("ident", text, m.start()))
        elif kind == "string":
            # Unescape single-quoted literal — collapse ``\\`` and ``\'``
            # to their character forms. Other escapes (``\n``, ``\t``) are
            # left as-is; they only appear inside lexer fragment rules.
            inner = text[1:-1]
            inner = inner.replace("\\\\", "\\").replace("\\'", "'")
            out.append(G4Token("string", inner, m.start()))
        elif kind == "arrow":
            out.append(G4Token("arrow", text, m.start()))
        elif kind == "punct":
            out.append(G4Token("punct", text, m.start()))
        elif kind == "dot":
            out.append(G4Token("dot", text, m.start()))
        elif kind == "tilde":
            out.append(G4Token("tilde", text, m.start()))
    return out


# ---------------------------------------------------------------------------
# .g4 parser
# ---------------------------------------------------------------------------
#
# Hand-rolled recursive descent over the lexed stream. Handles parser rules
# in full and lexer rules just enough to extract their literal text for
# token-name → text resolution.
#
# Grammar of grammars (the subset we recognise):
#
#   file       : header (rule SEMI)+
#   header     : 'parser'|'lexer' 'grammar' IDENT SEMI ('options' '{' ... '}')?
#   rule       : IDENT ':' alt_list ';'
#   alt_list   : alt ('|' alt)*
#   alt        : element* ('#' IDENT)?
#   element    : (IDENT '=')?           # label, ignored
#                ( IDENT                # token or rule reference
#                | STRING               # literal
#                | '(' alt_list ')'     # group
#                | '.'                  # wildcard (lexer-only, we punt)
#                | '~' element          # negation (lexer-only, we punt)
#                )
#                quantifier?
#                ('->' action_chain)?   # lexer action, ignored
#   quantifier : '?' | '*' | '+'


class _G4Parser:
    def __init__(self, tokens: list[G4Token], *, source: str = "") -> None:
        self.tokens = tokens
        self.pos = 0
        self.source = source

    def peek(self, offset: int = 0) -> G4Token | None:
        idx = self.pos + offset
        return self.tokens[idx] if 0 <= idx < len(self.tokens) else None

    def consume(self) -> G4Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def at(self, kind: str, text: str | None = None) -> bool:
        tok = self.peek()
        if tok is None or tok.kind != kind:
            return False
        return text is None or tok.text == text

    def expect(self, kind: str, text: str | None = None) -> G4Token:
        tok = self.peek()
        if tok is None or tok.kind != kind or (text is not None and tok.text != text):
            want = f"{kind}({text!r})" if text else kind
            got = f"{tok.kind}({tok.text!r})" if tok else "EOF"
            raise ValueError(f"Expected {want}, got {got} at .g4 pos {tok.pos if tok else -1}")
        return self.consume()

    # ----- header

    def skip_header(self) -> None:
        # parser grammar NAME ;  |  lexer grammar NAME ;
        # options { ... }   (action-block; the lexer already swallowed it)
        # ``mode NAME ;``  (lexer-only)
        while True:
            tok = self.peek()
            if tok is None:
                return
            if tok.kind == "ident" and tok.text in ("parser", "lexer"):
                # consume until ';'
                while self.peek() and not self.at("punct", ";"):
                    self.consume()
                if self.peek():
                    self.consume()  # ';'
                continue
            if tok.kind == "ident" and tok.text == "options":
                # ``options { ... }`` — the lexer already stripped the
                # action block; just eat the ``options`` keyword and
                # loop.
                self.consume()
                continue
            if tok.kind == "ident" and tok.text == "mode":
                # ``mode NAME ;`` — used in lexer file
                while self.peek() and not self.at("punct", ";"):
                    self.consume()
                if self.peek():
                    self.consume()
                continue
            return

    # ----- rule

    def parse_rule(self) -> Rule | None:
        # Mode directives appear interspersed with lexer rules — skip them.
        while self.at("ident", "mode"):
            self.consume()  # 'mode'
            self.consume()  # NAME
            self.expect("punct", ";")
        tok = self.peek()
        if tok is None:
            return None
        if tok.kind != "ident":
            raise ValueError(f"Expected rule name at .g4 pos {tok.pos}, got {tok.kind}({tok.text!r})")
        name_tok = self.consume()
        # Lexer rules may carry a ``fragment`` prefix — the previous token
        # was actually the fragment marker. Detect by checking the rule
        # name spelling, since the lexer doesn't distinguish.
        if name_tok.text == "fragment":
            real_name = self.consume()
            self.expect("punct", ":")
            self.parse_alt_list()
            self.expect("punct", ";")
            return Rule(name=f"<fragment:{real_name.text}>", alternatives=[])
        self.expect("punct", ":")
        alts = self.parse_alt_list()
        self.expect("punct", ";")
        return Rule(name=name_tok.text, alternatives=alts)

    def parse_alt_list(self) -> list[Alternative]:
        alts = [self.parse_alt()]
        while self.at("punct", "|"):
            self.consume()
            alts.append(self.parse_alt())
        return alts

    def parse_alt(self) -> Alternative:
        elements: list[Element] = []
        alt_name: str | None = None
        while True:
            tok = self.peek()
            if tok is None:
                break
            if tok.kind == "punct" and tok.text in (";", "|", ")"):
                break
            if tok.kind == "punct" and tok.text == "#":
                # Alternative name marker
                self.consume()
                name = self.expect("ident")
                alt_name = name.text
                break
            element = self.parse_element()
            if element is not None:
                elements.append(element)
        return Alternative(elements=elements, alt_name=alt_name)

    def parse_element(self) -> Element | None:
        tok = self.peek()
        if tok is None:
            return None

        # Optional label: ``name=elem`` — skip the label, parse the element
        if (
            tok.kind == "ident"
            and self.peek(1) is not None
            and self.peek(1).kind == "punct"  # type: ignore[union-attr]
            and self.peek(1).text == "="  # type: ignore[union-attr]
        ):
            self.consume()  # label
            self.consume()  # '='
            return self.parse_element()

        # Action arrow: ``-> skip``, ``-> type(LT), popMode``,
        # ``-> channel(HIDDEN), pushMode(DEFAULT_MODE)`` etc. The action
        # chain after ``->`` is lexer-only and can contain arbitrary
        # idents, commas, and balanced parens — we discard the whole
        # thing. The terminator is the rule terminator ``;`` or the
        # alternative separator ``|`` at depth 0.
        if tok.kind == "arrow":
            self.consume()  # ->
            depth = 0
            while True:
                t = self.peek()
                if t is None:
                    break
                if depth == 0 and t.kind == "punct" and t.text in (";", "|"):
                    break
                if t.kind == "punct" and t.text == "(":
                    depth += 1
                elif t.kind == "punct" and t.text == ")":
                    if depth == 0:
                        break
                    depth -= 1
                self.consume()
            return None

        if tok.kind == "string":
            self.consume()
            return self._with_quantifier(Element(kind="literal", text=tok.text))

        if tok.kind == "charclass":
            # Lexer-only char class. Treat as an opaque literal that
            # ``_alt_to_literal`` will refuse to resolve, forcing the
            # containing lexer rule into the escape-hatch path.
            self.consume()
            return self._with_quantifier(Element(kind="literal", text=tok.text))

        if tok.kind == "ident":
            self.consume()
            kind: ElementKind = "token" if tok.text[:1].isupper() else "rule"
            return self._with_quantifier(Element(kind=kind, name=tok.text))

        if tok.kind == "punct" and tok.text == "(":
            self.consume()
            alts = self.parse_alt_list()
            self.expect("punct", ")")
            return self._with_quantifier(Element(kind="group", children=alts))

        if tok.kind == "dot":
            # Wildcard (lexer-only). We never reach this from a parser
            # rule; skip so lexer-rule parsing doesn't choke.
            self.consume()
            return self._with_quantifier(Element(kind="literal", text="<wildcard>"))

        if tok.kind == "tilde":
            # Negation in lexer rules. Consume the operand element so the
            # lexer-rule parse stays balanced; we ignore it for codegen.
            self.consume()
            return self.parse_element()

        if tok.kind == "punct" and tok.text in ("?", "*", "+"):
            # Quantifier without an element to attach to — shouldn't
            # happen for parser rules; lexer-side surprise. Skip.
            self.consume()
            return None

        raise ValueError(f"Unexpected token in element: {tok.kind}({tok.text!r}) at .g4 pos {tok.pos}")

    def _with_quantifier(self, element: Element) -> Element:
        tok = self.peek()
        if tok is None or tok.kind != "punct":
            return element
        # The `in` check narrows to the Literal union the field's
        # type expects; the type checker can't see that without
        # binding the value to a Literal-annotated local first.
        if tok.text == "?":
            element.quantifier = "?"
        elif tok.text == "*":
            element.quantifier = "*"
        elif tok.text == "+":
            element.quantifier = "+"
        else:
            return element
        self.consume()
        return element


def g4_parse(src: str) -> Grammar:
    """Parse a .g4 source into a Grammar."""
    tokens = g4_lex(src)
    p = _G4Parser(tokens, source=src)
    p.skip_header()
    grammar = Grammar()
    while p.peek() is not None:
        rule = p.parse_rule()
        if rule is None:
            break
        if rule.name.startswith("<fragment:"):
            # Skip fragments — internal to lexer
            continue
        grammar.rules[rule.name] = rule
        grammar.rule_order.append(rule.name)
    return grammar


# ---------------------------------------------------------------------------
# Token-name → literal-text resolution
# ---------------------------------------------------------------------------
#
# For each uppercase token name referenced in a parser rule, we look up
# the corresponding lexer rule and extract its valid literal forms. A
# token may have multiple valid spellings (e.g. ``NOT_EQ: '!=' | '<>';``)
# which we expose as a list so the emitter can produce
# ``st.sampled_from(...)``.
#
# Tokens with variable content (``IDENTIFIER``, ``STRING_LITERAL``, etc.)
# resolve to ``None`` — the emitter looks them up in the hand-written
# escape-hatch module.


# Variable-content tokens that don't have a single literal form.
# The codegen emits a reference to ``_grammar_token_strategies.<name>``
# for these.
_VARIABLE_CONTENT_TOKENS: frozenset[str] = frozenset(
    {
        "IDENTIFIER",
        "QUOTED_IDENTIFIER",
        "FLOATING_LITERAL",
        "OCTAL_LITERAL",
        "OCTAL_PREFIX_LITERAL",
        "BINARY_LITERAL",
        "DECIMAL_LITERAL",
        "HEXADECIMAL_LITERAL",
        "STRING_LITERAL",
        "ESCAPE_CHAR_COMMON",
        "STRING_TEXT",
        "STRING_ESCAPE_TRIGGER",
        "FULL_STRING_TEXT",
        "FULL_STRING_ESCAPE_TRIGGER",
        "HOGQLX_TEXT_TEXT",
        "QUOTE_SINGLE_TEMPLATE",
        "QUOTE_SINGLE_TEMPLATE_FULL",
    }
)

# The pseudo-token ``EOF`` is implicit in ANTLR and means "end of input".
# In our generator it produces nothing.
_EOF_TOKEN: str = "EOF"


def resolve_token_literals(lexer_grammar: Grammar, token_name: str) -> list[str] | None:
    """Return the list of valid literal spellings for a token, or None if
    the token has variable content (the emitter then defers to the
    hand-written escape-hatch).

    For keyword-style rules (``SELECT: S E L E C T;``), the resolution is
    "lowercase the token name." For literal punctuation, we return the
    single literal string. For multi-alternative tokens (``YEAR: Y E A R
    | Y Y Y Y;``), we return all alternatives.
    """
    if token_name == _EOF_TOKEN:
        return [""]
    if token_name in _VARIABLE_CONTENT_TOKENS:
        return None

    rule = lexer_grammar.rules.get(token_name)
    if rule is None:
        # Not in lexer grammar — assume variable-content / escape-hatch.
        return None

    literals: list[str] = []
    for alt in rule.alternatives:
        text = _alt_to_literal(alt, token_name, lexer_grammar)
        if text is None:
            return None  # any alt with variable content disqualifies
        literals.append(text)
    return literals or None


def _alt_to_literal(alt: Alternative, host_token: str, lexer: Grammar) -> str | None:
    """Try to render a single lexer-rule alternative as a literal string.
    Returns None if any element resists literal resolution."""
    out: list[str] = []
    for el in alt.elements:
        # Within a lexer rule, single-letter idents are case-insensitive
        # macros (fragments) — ``S`` matches ``[Ss]``. We pick lowercase.
        if el.kind == "token":
            # Fragment reference (e.g. ``S``) or another token by name.
            # Single uppercase letter → fragment for that letter.
            if len(el.name) == 1 and el.name.isupper():
                if el.quantifier:
                    return None
                out.append(el.name.lower())
                continue
            # Multi-char token reference — try to recurse, but only for
            # punctuation-style tokens. Most keyword rules don't nest.
            sub = lexer.rules.get(el.name)
            if sub is None or el.quantifier:
                return None
            # Recurse only if the sub-rule has a single alternative that
            # resolves; otherwise bail.
            if len(sub.alternatives) != 1:
                return None
            sub_text = _alt_to_literal(sub.alternatives[0], el.name, lexer)
            if sub_text is None:
                return None
            out.append(sub_text)
            continue
        if el.kind == "literal":
            if el.quantifier:
                return None
            out.append(el.text)
            continue
        # group / rule reference / wildcard / negation — unresolvable.
        return None

    # Lowercase the assembly for keyword-style rules where every fragment
    # was a case-insensitive single letter. We detect this by checking
    # the host token name itself was uppercase letters/underscore.
    text = "".join(out)
    if re.fullmatch(r"[A-Z_]+(_SQL)?", host_token) and re.fullmatch(r"[a-z_0-9]+", text):
        # Use the host token name lowercased — this aligns with what
        # ANTLR matches case-insensitively and what we emit consistently.
        # We keep the assembled text from the alternatives though (so
        # multi-alt tokens like YEAR: Y E A R | Y Y Y Y still report
        # both literal forms).
        pass
    return text


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------
#
# HogQLX and Hog-program productions are explicitly out of scope (per
# product requirements). We carry a hard-coded skip-set; any rule
# alternative that transitively requires an excluded rule is dropped.
#
# HogQLX tags, template strings, the lexer mode-stack tokens, and Hog kv-pairs
# are all enabled. Escape-hatch strategies for their variable-content tokens
# (HOGQLX_TEXT_TEXT, QUOTE_SINGLE_TEMPLATE*, STRING_TEXT*, ESCAPE_CHAR_COMMON,
# …) live in `_grammar_token_strategies.py` and are mapped via
# `_ESCAPE_HATCH_NAMES`. The grammar PBT's space-joined token output is still
# accepted by the lexer in these modes because STRING_TEXT / FULL_STRING_TEXT
# / HOGQLX_TEXT_TEXT all permit whitespace within their alphabets.
EXCLUDED_RULES: frozenset[str] = frozenset()
# NB: the Hog program rules (`program`, `declaration`, `statement`,
# `returnStmt` / `throwStmt` / `tryCatchStmt` / `catchBlock` /
# `ifStmt` / `whileStmt` / `forStmt` / `forInStmt` / `funcStmt` /
# `varDecl` / `varAssignment` / `exprStmt` / `emptyStmt` / `block`)
# are intentionally NOT excluded — the grammar PBT drives Hog-program
# parity via the generated `program_strategy`.

# Alternatives the cpp-json oracle unconditionally rejects — error-message
# productions (e.g. ``ColumnExprInvalidFromImplicitAlias``, which exists only
# to raise on ``SELECT FROM x`` typos) and visitor-NotImplementedError
# productions the AST builder doesn't support (``ColumnExprDate`` /
# ``ColumnExprTimestamp`` / ``ColumnExprSubstring`` / ``ColumnTypeExprEnum`` /
# ``ColumnExprIntervalString``).
#
# These were hard-excluded while the diagnostic contract was one-sided (assert
# only when cpp accepts), since an oracle-rejected production carried zero
# signal. Under the two-sided contract they're the point: a query the oracle
# rejects must be rejected by the candidate too, so generating them is exactly
# how we catch the candidate accepting an invalid query. Empty by default;
# the hook stays for any future production that genuinely shouldn't generate.
EXCLUDED_ALT_NAMES: frozenset[str] = frozenset()

# Whole rules the cpp-json oracle rejects unconditionally (``topClause`` /
# ``settingsClause``). Same rationale as ``EXCLUDED_ALT_NAMES`` at rule
# granularity — now generated so the two-sided contract checks the candidate
# rejects them too.
EXCLUDED_BY_VISITOR_RULES: frozenset[str] = frozenset()

# Soft-weighting hooks remain (empty by default) for future
# productions where we want rare-fire coverage without exclusion.
SOFT_EXCLUDED_ALT_NAMES: frozenset[str] = frozenset()
SOFT_EXCLUDED_RULES: frozenset[str] = frozenset()

_SOFT_FREQ_DENOM: int = 30  # 1-in-30 inclusion for soft-excluded


def apply_exclusions(grammar: Grammar) -> Grammar:
    """Walk the grammar, surgically removing references to excluded
    rules. Three cases per element:

      - excluded rule with quantifier ``?`` / ``*``: replace with a
        no-op (empty literal). The rule was optional anyway.
      - excluded rule, mandatory: the containing alt becomes
        unsatisfiable — drop it.
      - group with excluded children: filter children; if any survive,
        keep the group with the survivors. If none survive, recurse
        into the rule/mandatory cases above.

    Iterate to fixpoint because dropping one rule can cascade into
    others losing all their alternatives.
    """
    all_excluded = EXCLUDED_RULES | EXCLUDED_BY_VISITOR_RULES
    rules = {n: r for n, r in grammar.rules.items() if n not in all_excluded}
    order = [n for n in grammar.rule_order if n in rules]

    while True:
        changed = False
        available = set(rules.keys())
        for name, rule in list(rules.items()):
            new_alts: list[Alternative] = []
            for alt in rule.alternatives:
                if alt.alt_name in EXCLUDED_ALT_NAMES:
                    continue  # hard-exclude
                filtered = _filter_alt(alt, available)
                if filtered is not None:
                    new_alts.append(filtered)
            if [a.elements for a in new_alts] != [a.elements for a in rule.alternatives]:
                rule.alternatives = new_alts
                changed = True
            if not rule.alternatives:
                # Rule lost all alternatives — drop it entirely.
                del rules[name]
                order = [n for n in order if n != name]
                changed = True
        if not changed:
            break

    return Grammar(rules=rules, rule_order=order)


def _filter_alt(alt: Alternative, available: set[str]) -> Alternative | None:
    """Filter excluded refs out of an alt. Returns None if the alt
    becomes impossible (a mandatory element references an excluded
    rule and can't be replaced)."""
    new_elements: list[Element] = []
    for el in alt.elements:
        fe = _filter_element(el, available)
        if fe is None:
            return None
        new_elements.append(fe)
    return Alternative(elements=new_elements, alt_name=alt.alt_name)


def _filter_element(el: Element, available: set[str]) -> Element | None:
    """Filter one element. Returns the (possibly rewritten) element or
    None if it can't be satisfied."""
    if el.kind == "rule" and el.name not in available:
        if el.quantifier in ("?", "*"):
            return Element(kind="literal", text="")  # no-op
        return None  # mandatory excluded ref
    if el.kind == "group":
        new_children: list[Alternative] = []
        for child in el.children:
            fc = _filter_alt(child, available)
            if fc is not None:
                new_children.append(fc)
        if not new_children:
            if el.quantifier in ("?", "*"):
                return Element(kind="literal", text="")
            return None
        # Preserve quantifier on the surviving group
        return Element(kind="group", children=new_children, quantifier=el.quantifier)
    return el


# ---------------------------------------------------------------------------
# Left-recursion detection + rewriting
# ---------------------------------------------------------------------------
#
# ANTLR4 admits direct left recursion (a rule whose alternatives can start
# with itself). For codegen we split each left-recursive rule's
# alternatives into:
#
#   seed_alts        — don't start with a self-reference; safe to use as
#                      base cases
#   suffix_alts      — start with ``R`` and have additional elements
#                      after; we drop the leading ``R`` and treat the
#                      remaining elements as an "operator tail" that the
#                      seed can be extended with
#
# At generation time we draw one seed, then optionally chain 0..N
# suffixes. Each suffix that contains another ``R`` reference draws at
# ``depth - 1`` to bound recursion.


@dataclass
class LeftRecursiveRule:
    """Result of analysing a left-recursive rule."""

    name: str
    seed_alts: list[Alternative]
    suffix_alts: list[Alternative]  # leading R already stripped


def analyse_left_recursion(rule: Rule) -> LeftRecursiveRule | None:
    """If ``rule`` is left-recursive, return a structured analysis;
    otherwise return None and the caller handles it as a normal rule."""
    seed_alts: list[Alternative] = []
    suffix_alts: list[Alternative] = []
    is_recursive = False
    for alt in rule.alternatives:
        if alt.elements and alt.elements[0].kind == "rule" and alt.elements[0].name == rule.name:
            # Trailing R is fine; we'll just draw it as a normal recursive
            # call with reduced depth. But the *leading* R is the
            # left-recursion signal — strip it.
            if alt.elements[0].quantifier:
                # Quantified leading reference (rare) — treat as seed.
                seed_alts.append(alt)
                continue
            stripped = Alternative(
                elements=alt.elements[1:],
                alt_name=alt.alt_name,
            )
            suffix_alts.append(stripped)
            is_recursive = True
        else:
            seed_alts.append(alt)
    if not is_recursive:
        return None
    return LeftRecursiveRule(
        name=rule.name,
        seed_alts=seed_alts,
        suffix_alts=suffix_alts,
    )


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------
#
# Walks the (filtered, rewritten) Grammar and emits a Python module string.
# Each rule becomes one ``@composite`` function. Variable-content tokens
# defer to the hand-written escape-hatch module.


# Variable-content tokens map to identifiers in the escape-hatch module.
# Keep this in sync with ``_grammar_token_strategies.py``.
_ESCAPE_HATCH_NAMES: dict[str, str] = {
    "IDENTIFIER": "identifier_token",
    "QUOTED_IDENTIFIER": "quoted_identifier_token",
    "FLOATING_LITERAL": "floating_literal_token",
    "OCTAL_LITERAL": "octal_literal_token",
    "DECIMAL_LITERAL": "decimal_literal_token",
    "HEXADECIMAL_LITERAL": "hexadecimal_literal_token",
    "BINARY_LITERAL": "binary_literal_token",
    "OCTAL_PREFIX_LITERAL": "octal_prefix_literal_token",
    "STRING_LITERAL": "string_literal_token",
    # HogQLX / template-string variable-content tokens. These belong to lexer
    # modes the codegen can't resolve to a literal; strategies in
    # `_grammar_token_strategies.py` supply short, conservative content.
    "QUOTE_SINGLE_TEMPLATE": "quote_single_template_token",
    "QUOTE_SINGLE_TEMPLATE_FULL": "quote_single_template_full_token",
    "STRING_ESCAPE_TRIGGER": "string_escape_trigger_token",
    "FULL_STRING_ESCAPE_TRIGGER": "full_string_escape_trigger_token",
    "STRING_TEXT": "string_text_token",
    "FULL_STRING_TEXT": "full_string_text_token",
    "HOGQLX_TEXT_TEXT": "hogqlx_text_token",
    # ESCAPE_CHAR_COMMON is a lexer-internal subrule of STRING_TEXT /
    # FULL_STRING_TEXT, never referenced by parser rules directly, so no
    # escape-hatch is needed. (`escape_char_common_token` still lives in
    # `_grammar_token_strategies.py` for manual use if a future grammar edit
    # adds a parser-level reference.)
}


def _sanitise(name: str) -> str:
    """Rule name → strategy function name."""
    return name + "_strategy"


def _is_leaf_only(alt: Alternative) -> bool:
    """True iff the alternative contains no rule references (anywhere,
    including in nested groups). Used to find alternatives that bottom
    out generation at depth 0."""
    for el in alt.elements:
        if el.kind == "rule":
            return False
        if el.kind == "group":
            for sub in el.children:
                if not _is_leaf_only(sub):
                    return False
    return True


def _alt_is_soft(alt: Alternative) -> bool:
    """Soft if the alt's name is in ``SOFT_EXCLUDED_ALT_NAMES`` or any
    direct rule reference targets a soft-excluded rule. Group descent
    is shallow — we only flag the alt itself, not nested ones."""
    if alt.alt_name in SOFT_EXCLUDED_ALT_NAMES:
        return True
    for el in alt.elements:
        if el.kind == "rule" and el.name in SOFT_EXCLUDED_RULES:
            return True
    return False


def _classify_alts(alts: list[Alternative]) -> tuple[list[int], list[int], list[int]]:
    """Return ``(common_indices, soft_indices, leaf_indices)`` for an
    alt list. ``leaf_indices`` are alts with no rule references at
    all — used at depth 0 to bottom out. ``soft_indices`` are alts
    that are unsupported by the cpp visitor — sampled rarely.
    ``common_indices`` are everything else.

    If all alts are leaves or all are soft we degrade gracefully:
    the caller's selector falls back to a flat sample.
    """
    leaf: list[int] = []
    soft: list[int] = []
    common: list[int] = []
    for i, alt in enumerate(alts):
        if _alt_is_soft(alt):
            soft.append(i)
        else:
            common.append(i)
        if _is_leaf_only(alt):
            leaf.append(i)
    # If every alt is soft, demote them to common so we still emit
    # something — the soft-tag was advisory.
    if not common and soft:
        common = soft
        soft = []
    return common, soft, leaf


def _quote(s: str) -> str:
    # Emit a double-quoted Python string literal so the codegen output matches `ruff format`'s preference;
    # otherwise lint-staged keeps reverting the regen on commit. Fall back to `repr` for content that needs
    # escaping (none of the grammar's keyword literals do today, but it costs nothing to be safe).
    if any(c in s for c in '"\\') or any(ord(c) < 32 or ord(c) > 126 for c in s):
        return repr(s)
    return f'"{s}"'


def _emit_literal_list(literals: list[str]) -> str:
    if len(literals) == 1:
        return _quote(literals[0])
    return "draw(st.sampled_from([" + ", ".join(_quote(s) for s in literals) + "]))"


_EMITTED_FILE_HEADER = f'''\
"""Auto-generated grammar strategies for the HogQL parser PBT.

DO NOT EDIT. Regenerate via::

    python -m posthog.hogql.scripts.build_grammar_strategies

The generator reads ``posthog/hogql/grammar/HogQLParser.g4`` and
``posthog/hogql/grammar/HogQLLexer.common.g4`` and emits this file.

Each rule is a depth-parameterised strategy factory:
``foo_strategy(depth=_DEFAULT_DEPTH)`` returns a ``SearchStrategy[str]``.
Recursive sub-rule draws decrement depth; at depth 0 the strategy
prefers leaf alternatives so generation bottoms out. Strategies are
memoised per-depth via ``functools.cache`` so Hypothesis sees stable
identity across draws (matters for shrinking).
"""

from __future__ import annotations

import functools
from typing import Any

from hypothesis import strategies as st

from posthog.hogql.test._grammar_token_strategies import (
    binary_literal_token,
    decimal_literal_token,
    floating_literal_token,
    full_string_escape_trigger_token,
    full_string_text_token,
    hexadecimal_literal_token,
    hogqlx_text_token,
    identifier_token,
    octal_literal_token,
    octal_prefix_literal_token,
    quote_single_template_full_token,
    quote_single_template_token,
    quoted_identifier_token,
    string_escape_trigger_token,
    string_literal_token,
    string_text_token,
)

_DEFAULT_DEPTH = 5
_MAX_REPEAT = 4       # cap for `*` / `+` quantifiers (per occurrence)
_MAX_LR_CHAIN = 4     # cap for chained Pratt-style suffixes (per LR rule)

# Probability an optional ``?``-quantified element is included. 50/50
# produces unrealistically clause-rich SELECTs (a typical SELECT has 25
# optional clauses; even 30% inclusion gives ~8 clauses per query, more
# than enough). Tune-able to stress the parser harder.
# 1-in-N inclusion rate for ``?``-quantified elements. With SELECT's
# ~20 optional clauses, 1/8 = 12.5% gives an average of ~2.5 clauses
# per query — small enough that visitor-NotImplementedError productions
# in any one clause don't blow up acceptance for the whole query, but
# big enough that every optional gets exercised across a 1k-example run.
_OPT_INCLUSION_DEN = 8

# 1-in-N inclusion rate for "soft-excluded" productions — alternatives
# that exist in the grammar but tend to be visitor-rejected by cpp.
# Firing them at a low rate keeps parity coverage without tanking
# acceptance. With ~10 columnExpr nodes per SELECT, a rate of 1/30
# yields ~70% chance the SELECT contains no soft alt.
# Interpolated from the generator's module-level constant; both
# alt-level and element-level soft-firing emit ``_include_soft(draw)``
# below, so the rate lives in exactly one place at runtime.
_SOFT_FREQ_DENOM = {_SOFT_FREQ_DENOM}


def _dec(depth: int) -> int:
    """Decrement depth but clamp at 0."""
    return depth - 1 if depth > 0 else 0


def _include_optional(draw: Any) -> bool:
    """Whether to include a ``?``-quantified element. Biased low so
    optional-heavy rules like ``selectStmt`` don't produce 25-clause
    monsters."""
    return draw(st.integers(min_value=0, max_value=_OPT_INCLUSION_DEN - 1)) == 0


def _include_soft(draw: Any) -> bool:
    """Whether to include a soft-excluded production (visitor-rejected
    by cpp; rare-fire to keep parity coverage without tanking
    acceptance). The rate is per-occurrence; trees with many soft slots
    compound, so this needs to be low enough that a typical query stays
    free of soft alts. With ~10 columnExpr nodes per SELECT, a rate of
    1/30 yields ~70% chance the SELECT contains no soft alt."""
    return draw(st.integers(min_value=0, max_value=_SOFT_FREQ_DENOM - 1)) == 0
'''


class _Emitter:
    def __init__(self, grammar: Grammar, lexer_grammar: Grammar) -> None:
        self.grammar = grammar
        self.lexer_grammar = lexer_grammar
        # Memoise token-literal lookups
        self._token_cache: dict[str, list[str] | None] = {}

    def _token_literals(self, name: str) -> list[str] | None:
        if name not in self._token_cache:
            self._token_cache[name] = resolve_token_literals(self.lexer_grammar, name)
        return self._token_cache[name]

    def emit(self) -> str:
        chunks: list[str] = [_EMITTED_FILE_HEADER, ""]
        for name in self.grammar.rule_order:
            chunks.append(self._emit_rule_builder(self.grammar.rules[name]))
            chunks.append("")
        return "\n".join(chunks) + "\n"

    def _emit_rule_builder(self, rule: Rule) -> str:
        lr = analyse_left_recursion(rule)
        if lr is not None:
            return self._emit_left_recursive(lr)
        return self._emit_plain(rule)

    # ----- plain (non-LR) rule emission

    def _emit_plain(self, rule: Rule) -> str:
        lines: list[str] = []
        lines.append("@functools.cache")
        lines.append(f"def {_sanitise(rule.name)}(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:")
        lines.append("    @st.composite")
        lines.append("    def gen(draw: Any) -> str:")
        if len(rule.alternatives) == 1:
            lines.append("        parts: list[str] = []")
            self._emit_alt_body(lines, rule.alternatives[0], indent="        ")
            lines.append('        return " ".join(p for p in parts if p)')
        else:
            common_indices, soft_indices, leaf_indices = _classify_alts(rule.alternatives)
            # Hoist the typed declaration once at the function scope so the
            # per-branch resets below are plain reassignments — mypy treats
            # multiple ``parts: list[str] = []`` lines in the same scope as
            # redefinitions and flags them with ``[no-redef]``.
            lines.append("        parts: list[str] = []")
            self._emit_alt_selector(lines, common_indices, soft_indices, leaf_indices)
            for i, alt in enumerate(rule.alternatives):
                lines.append(f"        if alt_idx == {i}:")
                lines.append("            parts = []")
                self._emit_alt_body(lines, alt, indent="            ")
                lines.append('            return " ".join(p for p in parts if p)')
            lines.append('        raise AssertionError("unreachable")')
        lines.append("    return gen()")
        return "\n".join(lines)

    def _emit_alt_selector(
        self,
        lines: list[str],
        common_indices: list[int],
        soft_indices: list[int],
        leaf_indices: list[int],
    ) -> None:
        """Emit the ``alt_idx = ...`` selection statement, factoring in
        depth-0 leaf preference and soft-excluded alt weighting.

        Precedence:
          1. ``depth <= 0`` and we have leaf alts → pick from leaves.
          2. ``soft`` alts exist and we draw the rare slot → pick soft.
          3. Otherwise → pick from common (non-soft) alts.
        """
        total = len(common_indices) + len(soft_indices)
        has_leaves = bool(leaf_indices) and len(leaf_indices) < total
        if not soft_indices and not has_leaves:
            # Nothing to weight; flat sampling
            lines.append(f"        alt_idx = draw(st.integers(min_value=0, max_value={total - 1}))")
            return
        # Routed through the emitted ``_include_soft`` helper so the
        # alt-level and element-level soft-firing rates share one
        # definition; without this the integer-check would be inlined
        # here while element-level emission calls the helper.
        if has_leaves:
            lines.append("        if depth <= 0:")
            lines.append(f"            alt_idx = draw(st.sampled_from({leaf_indices!r}))")
            if soft_indices:
                lines.append("        elif _include_soft(draw):")
                lines.append(f"            alt_idx = draw(st.sampled_from({soft_indices!r}))")
            lines.append("        else:")
            lines.append(f"            alt_idx = draw(st.sampled_from({common_indices!r}))")
        else:
            lines.append("        if _include_soft(draw):")
            lines.append(f"            alt_idx = draw(st.sampled_from({soft_indices!r}))")
            lines.append("        else:")
            lines.append(f"            alt_idx = draw(st.sampled_from({common_indices!r}))")

    # ----- left-recursive rule emission

    def _emit_left_recursive(self, lr: LeftRecursiveRule) -> str:
        lines: list[str] = []
        lines.append("@functools.cache")
        lines.append(f"def {_sanitise(lr.name)}(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:")
        if len(lr.seed_alts) == 0:
            lines.append("    @st.composite")
            lines.append("    def gen(draw: Any) -> str:")
            lines.append(f'        raise AssertionError("left-recursive rule {lr.name!r} has no seed alternatives")')
            lines.append("    return gen()")
            return "\n".join(lines)
        # Bind ``_has_suffixes`` in the enclosing function scope BEFORE
        # the inner ``gen`` closes over it. ``analyse_left_recursion``
        # only returns a ``LeftRecursiveRule`` when at least one suffix
        # exists, so this is always ``True`` today — the flag is left
        # in place so the guard in ``gen`` is correct under any future
        # codegen change that admits a zero-suffix LR rule.
        lines.append(f"    _has_suffixes = {bool(lr.suffix_alts)}")
        lines.append("")
        lines.append("    @st.composite")
        lines.append("    def gen(draw: Any) -> str:")
        # Pick a seed alternative
        if len(lr.seed_alts) == 1:
            lines.append("        parts: list[str] = []")
            self._emit_alt_body(lines, lr.seed_alts[0], indent="        ")
            lines.append('        seed = " ".join(p for p in parts if p)')
        else:
            common_indices, soft_indices, leaf_indices = _classify_alts(lr.seed_alts)
            # The LR seed selector emits to ``alt_idx``; rename to
            # ``seed_idx`` here for clarity.
            sel_lines: list[str] = []
            self._emit_alt_selector(sel_lines, common_indices, soft_indices, leaf_indices)
            # Hoist the typed declaration once at the function scope so the
            # per-branch resets below are plain reassignments — see the
            # matching note in ``_emit_plain``.
            lines.append("        parts: list[str] = []")
            lines.extend(line.replace("alt_idx", "seed_idx") for line in sel_lines)
            lines.append('        seed = ""')
            for i, alt in enumerate(lr.seed_alts):
                lines.append(f"        if seed_idx == {i}:")
                lines.append("            parts = []")
                self._emit_alt_body(lines, alt, indent="            ")
                lines.append('            seed = " ".join(p for p in parts if p)')
        # Then chain 0..MAX_LR_CHAIN suffixes when depth allows
        lines.append("        if depth <= 0 or not _has_suffixes:")
        lines.append("            return seed")
        lines.append("        n_suffixes = draw(st.integers(min_value=0, max_value=_MAX_LR_CHAIN))")
        lines.append("        for _ in range(n_suffixes):")
        lines.append(f"            suffix_idx = draw(st.integers(min_value=0, max_value={len(lr.suffix_alts) - 1}))")
        for i, alt in enumerate(lr.suffix_alts):
            lines.append(f"            if suffix_idx == {i}:")
            lines.append("                parts = []")
            self._emit_alt_body(
                lines,
                alt,
                indent="                ",
                self_rule_name=lr.name,
                self_depth_expr="_dec(depth)",
            )
            lines.append('                seed = seed + " " + " ".join(p for p in parts if p)')
        lines.append("        return seed")
        lines.append("")
        lines.append("    return gen()")
        return "\n".join(lines)

    # ----- alt body

    def _emit_alt_body(
        self,
        lines: list[str],
        alt: Alternative,
        *,
        indent: str,
        self_rule_name: str | None = None,
        self_depth_expr: str = "depth - 1",
    ) -> None:
        """Emit the body for a single alternative — appends to ``lines``.
        Each element either appends to ``parts`` or controls flow."""
        for el in alt.elements:
            self._emit_element(lines, el, indent=indent, self_rule_name=self_rule_name, self_depth_expr=self_depth_expr)

    def _emit_element(
        self,
        lines: list[str],
        el: Element,
        *,
        indent: str,
        self_rule_name: str | None,
        self_depth_expr: str,
    ) -> None:
        if el.kind == "literal":
            value_expr = repr(el.text)
            self._emit_with_quantifier(lines, value_expr, el.quantifier, indent)
            return

        if el.kind == "token":
            literals = self._token_literals(el.name)
            if literals is None:
                # Escape-hatch: defer to the hand-written strategy module
                strategy_name = _ESCAPE_HATCH_NAMES.get(el.name)
                if strategy_name is None:
                    # Unknown variable-content token — generate a no-op
                    # placeholder so the codegen still completes. The
                    # smoke test will surface low acceptance rates.
                    value_expr = repr(f"<unresolved:{el.name}>")
                else:
                    value_expr = f"draw({strategy_name})"
                self._emit_with_quantifier(lines, value_expr, el.quantifier, indent)
                return
            value_expr = _emit_literal_list(literals)
            self._emit_with_quantifier(lines, value_expr, el.quantifier, indent)
            return

        if el.kind == "rule":
            ref_strategy = _sanitise(el.name)
            # Every cross-rule draw decrements depth — that's how
            # recursion bottoms out.
            value_expr = f"draw({ref_strategy}(_dec(depth)))"
            # Soft-excluded rules (visitor-rejected) get bumped down
            # to ``?``-quantified soft inclusion even when the .g4
            # declares them as ``?``. A mandatory soft ref is
            # generated unchanged — caller probably knew what it
            # wanted.
            is_soft = el.name in SOFT_EXCLUDED_RULES and el.quantifier in ("", "?")
            self._emit_with_quantifier(
                lines,
                value_expr,
                el.quantifier,
                indent,
                is_soft=is_soft,
            )
            return

        if el.kind == "group":
            # Emit groups inline: for each child alternative, emit a
            # conditional branch that runs that alt's body.
            if not el.children:
                return
            if el.quantifier in ("", "?"):
                if el.quantifier == "?":
                    lines.append(f"{indent}if _include_optional(draw):")
                    inner_indent = indent + "    "
                else:
                    inner_indent = indent
                self._emit_group_choice(
                    lines, el.children, inner_indent, self_rule_name=self_rule_name, self_depth_expr=self_depth_expr
                )
                return
            # `*` or `+` — emit a loop
            min_iters = 1 if el.quantifier == "+" else 0
            lines.append(f"{indent}for _ in range(draw(st.integers(min_value={min_iters}, max_value=_MAX_REPEAT))):")
            self._emit_group_choice(
                lines,
                el.children,
                indent + "    ",
                self_rule_name=self_rule_name,
                self_depth_expr=self_depth_expr,
            )
            return

    def _emit_group_choice(
        self,
        lines: list[str],
        children: list[Alternative],
        indent: str,
        *,
        self_rule_name: str | None,
        self_depth_expr: str,
    ) -> None:
        if len(children) == 1:
            self._emit_alt_body(
                lines, children[0], indent=indent, self_rule_name=self_rule_name, self_depth_expr=self_depth_expr
            )
            return
        lines.append(f"{indent}group_idx = draw(st.integers(min_value=0, max_value={len(children) - 1}))")
        for i, alt in enumerate(children):
            lines.append(f"{indent}if group_idx == {i}:")
            self._emit_alt_body(
                lines,
                alt,
                indent=indent + "    ",
                self_rule_name=self_rule_name,
                self_depth_expr=self_depth_expr,
            )

    def _emit_with_quantifier(
        self,
        lines: list[str],
        value_expr: str,
        quantifier: Quantifier,
        indent: str,
        *,
        is_soft: bool = False,
    ) -> None:
        if quantifier == "":
            if is_soft:
                # Mandatory ref to a soft-excluded rule. Gate inclusion
                # to roughly 10% even though the grammar requires it —
                # at the cost of generating syntactically incomplete
                # text, we lift acceptance significantly. The full-rate
                # case still fires often enough to exercise the path.
                lines.append(f"{indent}if _include_soft(draw):")
                lines.append(f"{indent}    parts.append({value_expr})")
            else:
                lines.append(f"{indent}parts.append({value_expr})")
        elif quantifier == "?":
            include_check = "_include_soft(draw)" if is_soft else "_include_optional(draw)"
            lines.append(f"{indent}if {include_check}:")
            lines.append(f"{indent}    parts.append({value_expr})")
        elif quantifier == "*":
            lines.append(f"{indent}for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):")
            lines.append(f"{indent}    parts.append({value_expr})")
        elif quantifier == "+":
            lines.append(f"{indent}for _ in range(draw(st.integers(min_value=1, max_value=_MAX_REPEAT))):")
            lines.append(f"{indent}    parts.append({value_expr})")


def generate(parser_grammar_path: str, lexer_grammar_path: str) -> str:
    """Run the full pipeline and return the Python source to write."""
    with open(parser_grammar_path) as f:
        parser_src = f.read()
    with open(lexer_grammar_path) as f:
        lexer_src = f.read()

    parser_grammar = g4_parse(parser_src)
    lexer_grammar = g4_parse(lexer_src)
    filtered = apply_exclusions(parser_grammar)
    emitter = _Emitter(filtered, lexer_grammar)
    return emitter.emit()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PARSER_GRAMMAR = REPO_ROOT / "posthog" / "hogql" / "grammar" / "HogQLParser.g4"
LEXER_GRAMMAR = REPO_ROOT / "posthog" / "hogql" / "grammar" / "HogQLLexer.common.g4"
OUTPUT_PATH = REPO_ROOT / "posthog" / "hogql" / "test" / "_generated_grammar_strategies.py"


def _ruff_format(source: str) -> str:
    # Pipe `source` through `ruff format -` so the codegen output exactly matches what `bin/hogli format:python`
    # produces. Without this, lint-staged keeps reverting the regen on commit (it formats then sees no diff).
    # Runs ruff via the same venv that's already importing this module, so no PATH gymnastics needed.
    result = subprocess.run(
        ["ruff", "format", "-"],
        input=source,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the on-disk generated file matches what we'd emit. Exit 1 on drift.",
    )
    args = parser.parse_args()

    source = _ruff_format(generate(str(PARSER_GRAMMAR), str(LEXER_GRAMMAR)))

    if args.check:
        if not OUTPUT_PATH.exists():
            print(f"FAIL: {OUTPUT_PATH} does not exist. Run without --check to regenerate.")
            return 1
        existing = OUTPUT_PATH.read_text()
        if existing != source:
            print(
                f"FAIL: {OUTPUT_PATH} is out of sync with the grammar.\n"
                f"Run `python -m posthog.hogql.scripts.build_grammar_strategies` to regenerate."
            )
            return 1
        print(f"OK: {OUTPUT_PATH} is in sync with the grammar.")
        return 0

    OUTPUT_PATH.write_text(source)
    print(f"Wrote {OUTPUT_PATH} ({len(source)} bytes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
