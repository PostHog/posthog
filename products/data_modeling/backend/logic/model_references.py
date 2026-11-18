import re

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.escape_sql import escape_hogql_identifier
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor, clear_locations

from posthog.dataclasses import frozen


class ModelReferenceRewriteError(ValueError):
    pass


@frozen
class _Reference:
    field: ast.Field
    prefix_length: int
    replacement: tuple[str, ...]


@frozen
class _Splice:
    start: int
    end: int
    text: str


class _ModelReferenceFinder(TraversingVisitor):
    """Walk only the user's parse tree, never a resolved view's expanded body."""

    def __init__(self, replacements: dict[tuple[str, ...], tuple[str, ...]]) -> None:
        super().__init__()
        self.replacements = replacements
        self.ctes: set[str] = set()
        self.qualifiers: dict[str, tuple[str, ...]] = {}
        self.table_fields: set[int] = set()
        self.references: list[_Reference] = []

    def _replacement(self, table: ast.Field) -> tuple[str, ...] | None:
        chain = tuple(str(part) for part in table.chain)
        if ".".join(chain) in self.ctes:
            return None
        if len(chain) == 1:
            chain = tuple(chain[0].split("."))
        return self.replacements.get(chain)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        previous_ctes = self.ctes
        self.ctes = self.ctes | set(node.ctes or {})
        previous = self.qualifiers
        self.qualifiers = {}
        join = node.select_from
        while join is not None:
            if isinstance(join.table, ast.Field) and join.alias is None:
                if replacement := self._replacement(join.table):
                    self.qualifiers["__".join(str(part) for part in join.table.chain)] = replacement
            join = join.next_join
        try:
            super().visit_select_query(node)
        finally:
            self.qualifiers = previous
            self.ctes = previous_ctes

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field):
            self.table_fields.add(id(node.table))
            if replacement := self._replacement(node.table):
                self.references.append(
                    _Reference(field=node.table, prefix_length=len(node.table.chain), replacement=replacement)
                )
        super().visit_join_expr(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        first = node.initial_select_query
        while isinstance(first, ast.SelectSetQuery):
            first = first.initial_select_query
        previous_ctes = self.ctes
        self.ctes = self.ctes | set(first.ctes or {})
        try:
            super().visit_select_set_query(node)
        finally:
            self.ctes = previous_ctes

    def visit_field(self, node: ast.Field) -> None:
        if id(node) in self.table_fields or len(node.chain) < 2:
            return
        replacement = self.qualifiers.get(str(node.chain[0]))
        consumed = 1
        if replacement is None:
            parts: list[str] = []
            for length, segment in enumerate(node.chain[:-1], start=1):
                parts.extend(str(segment).split("."))
                if len(parts) > 1 and (match := self.qualifiers.get("__".join(parts))):
                    replacement, consumed = match, length
        if replacement is not None:
            self.references.append(_Reference(field=node, prefix_length=consumed, replacement=replacement))


class _Fields(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.fields: list[ast.Field] = []

    def visit_field(self, node: ast.Field) -> None:
        self.fields.append(node)


# Keep trivia outside identifier edits, including comments between chain segments.
_FIELD_TOKEN = re.compile(
    r"(?P<trivia>\s+|--[^\n]*(?:\n|$)|/\*.*?\*/)|(?P<identifier>`(?:\\.|``|[^`])*`|\"(?:\\.|\"\"|[^\"])*\"|[\w$]+|\*)|(?P<dot>\.)",
    re.DOTALL,
)


def _splice_reference(query: str, reference: _Reference) -> list[_Splice]:
    node = reference.field
    if node.start is None or node.end is None:
        raise ModelReferenceRewriteError("Parse check failed. The reference has no source location.")
    tokens = list(_FIELD_TOKEN.finditer(query, node.start, node.end))
    if not tokens or "".join(token.group() for token in tokens) != query[node.start : node.end]:
        raise ModelReferenceRewriteError("Parse check failed. The reference does not match its source text.")
    identifiers = [token for token in tokens if token.lastgroup == "identifier"]
    if len(identifiers) != len(node.chain):
        raise ModelReferenceRewriteError("Parse check failed. The reference does not match its source text.")
    # Align the trailing segments so qualification preserves the author's existing quotes and spacing.
    count = reference.prefix_length
    replacement = reference.replacement
    extra = len(replacement) - count
    edits: list[_Splice] = []
    for index, token in enumerate(identifiers[:count]):
        new_index = index + extra
        if new_index < 0:
            text = ""
            dot = next((part for part in tokens if part.lastgroup == "dot" and part.start() > token.end() - 1), None)
            if dot is None:
                raise ModelReferenceRewriteError("Parse check failed. The reference has no separator.")
            edits.append(_Splice(start=dot.start(), end=dot.end(), text=""))
        else:
            text = (
                token.group()
                if str(node.chain[index]) == replacement[new_index]
                else escape_hogql_identifier(replacement[new_index])
            )
            if index == 0 and extra > 0:
                text = ".".join(escape_hogql_identifier(part) for part in replacement[:extra]) + "." + text
        edits.append(_Splice(start=token.start(), end=token.end(), text=text))
    return edits


def _rewrite(query: str, replacements: dict[tuple[str, ...], tuple[str, ...]]) -> str:
    try:
        original = parse_select(query)
    except BaseHogQLError as error:
        raise ModelReferenceRewriteError("Query does not parse. Fix the query before renaming the model.") from error
    finder = _ModelReferenceFinder(replacements)
    finder.visit(original)
    if not finder.references:
        return query

    edits = [edit for reference in finder.references for edit in _splice_reference(query, reference)]
    result = query
    for edit in sorted(edits, key=lambda edit: edit.start, reverse=True):
        result = result[: edit.start] + edit.text + result[edit.end :]
    try:
        checked = parse_select(result)
    except BaseHogQLError as error:
        raise ModelReferenceRewriteError("Parse check failed. The rewritten query does not parse.") from error

    before, after = _Fields(), _Fields()
    before.visit(original)
    after.visit(checked)
    replacements_by_field = {id(ref.field): ref for ref in finder.references}
    if len(before.fields) != len(after.fields):
        raise ModelReferenceRewriteError("Parse check failed. The rewritten query has a different structure.")
    for old, new in zip(before.fields, after.fields):
        if reference := replacements_by_field.get(id(old)):
            expected = [*reference.replacement, *old.chain[reference.prefix_length :]]
            if new.chain != expected:
                raise ModelReferenceRewriteError("Parse check failed. The rewritten reference differs from the plan.")
            new.chain = old.chain.copy()
    if clear_locations(original) != clear_locations(checked):
        raise ModelReferenceRewriteError("Parse check failed. The rewritten query has a different structure.")
    return result


def rewrite_model_references(query: str, spellings: set[tuple[str, ...]], new: tuple[str, ...]) -> str:
    return _rewrite(query, dict.fromkeys(spellings, new))


def qualify_model_references(query: str, database: Database) -> str:
    """Canonicalize model references on save; leave unparseable queries as written."""
    replacements: dict[tuple[str, ...], tuple[str, ...]] = {}
    for name in database.get_view_names():
        if not name.startswith("models."):
            continue
        qualified = tuple(name.split("."))
        bare = qualified[1:]
        try:
            if database.get_table_node(list(bare)) is database.get_table_node(list(qualified)):
                replacements[bare] = qualified
        except BaseHogQLError:
            continue
    try:
        return _rewrite(query, replacements)
    except ModelReferenceRewriteError:
        return query
