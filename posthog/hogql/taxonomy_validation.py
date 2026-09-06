from dataclasses import dataclass
from difflib import get_close_matches
from logging import getLogger
from math import ceil, floor
from typing import Literal

from django.db import DatabaseError
from django.db.models import QuerySet
from django.db.models.functions import Length

from posthog.schema import HogQLNotice

from posthog.hogql import ast
from posthog.hogql.escape_sql import escape_hogql_identifier, escape_hogql_string
from posthog.hogql.visitor import TraversingVisitor

from posthog.models import EventDefinition, PropertyDefinition, Team

from products.event_definitions.backend.models.property_definition import effective_project_id_expr

logger = getLogger(__name__)

# How a suggested name is rendered back into the marked range for a one-click fix:
# `string` → a quoted, escaped string literal (event `=`/`IN` values, `properties['key']` keys);
# `property` → a `properties.<identifier>` field. Both escape the suggestion (see `_build_fix`).
FixContext = Literal["string", "property"]

# How many project-scoped names one suggestion lookup reads. A project holds hundreds to low
# thousands of definitions, and the length band below drops most of those, so the cap only binds on
# a project whose taxonomy is far larger than that.
SUGGESTION_CANDIDATE_LIMIT = 2000

# How close a candidate must be to earn a "Did you mean". `difflib` scores a pair as
# `2 * matching_characters / (len(a) + len(b))`.
SIMILARITY_CUTOFF = 0.6

# The `name` column of both definition models is `CharField(max_length=400)`.
MAX_SUGGESTION_INPUT_LENGTH = 400

# How many unknown names in one query get a suggestion. One lookup covers the whole batch, but every
# name in it is compared against every candidate, and a caller controls how many unknown names one
# query carries. Names past this cap still warn, only without "Did you mean".
MAX_SUGGESTED_NAMES = 5

# Property names that are legitimately dynamic — they encode an id/key after the prefix, so they will
# never appear in PropertyDefinition and must not be flagged as unknown.
DYNAMIC_PROPERTY_PREFIXES = (
    "$feature/",
    "$feature_enrollment/",
    "$survey_responded/",
    "$survey_dismissed/",
)


@dataclass(frozen=True)
class TaxonomyReference:
    name: str
    start: int | None = None
    end: int | None = None
    # The `start`/`end` range covers the whole token in source (quotes, `properties.` prefix and all),
    # so a quick-fix that replaces that range must rebuild the whole token — not just the bare name — or
    # it strips the quotes/prefix. `fix_context` says how to render the suggested name back into that slot.
    # `None` means "warn, but offer no one-click fix" (e.g. nested `properties.a.b`).
    fix_context: FixContext | None = "string"


class TaxonomyReferenceVisitor(TraversingVisitor):
    def __init__(self):
        self.event_literals: list[TaxonomyReference] = []
        self.property_names: list[TaxonomyReference] = []

    def visit_compare_operation(self, node: ast.CompareOperation):
        self._collect_event_comparison(node)
        super().visit_compare_operation(node)

    def visit_field(self, node: ast.Field):
        self._collect_property_field(node)
        super().visit_field(node)

    def visit_array_access(self, node: ast.ArrayAccess):
        self._collect_property_array_access(node)
        super().visit_array_access(node)

    def _collect_event_comparison(self, node: ast.CompareOperation) -> None:
        if node.op == ast.CompareOperationOp.Eq:
            reference = _event_literal_from_equality(node.left, node.right) or _event_literal_from_equality(
                node.right, node.left
            )
            if reference:
                self.event_literals.append(reference)
            return

        if node.op in {ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn} and _is_event_field(node.left):
            self.event_literals.extend(_string_literals_from_array(node.right))

    def _collect_property_field(self, node: ast.Field) -> None:
        if len(node.chain) >= 2 and node.chain[0] == "properties" and isinstance(node.chain[1], str):
            # The range spans the whole `properties.<name>` field, so the fix must too. Only offer it
            # for the simple two-segment shape; a nested `properties.a.b` would need to keep the suffix.
            fix_context: FixContext | None = "property" if len(node.chain) == 2 else None
            self.property_names.append(TaxonomyReference(node.chain[1], node.start, node.end, fix_context=fix_context))

    def _collect_property_array_access(self, node: ast.ArrayAccess) -> None:
        if (
            _is_properties_field(node.array)
            and isinstance(node.property, ast.Constant)
            and isinstance(node.property.value, str)
        ):
            self.property_names.append(
                TaxonomyReference(node.property.value, node.property.start, node.property.end, fix_context="string")
            )


def validate_taxonomy_references(
    query: ast.SelectQuery | ast.SelectSetQuery, team: Team, table_names: list[str] | None = None
) -> list[HogQLNotice]:
    visitor = TaxonomyReferenceVisitor()
    visitor.visit(query)

    if table_names is not None and "events" not in table_names:
        return []

    if not visitor.event_literals and not visitor.property_names:
        return []

    warnings: list[HogQLNotice] = []

    # Taxonomy validation is an advisory signal: fail open. A transient DB error during the lookup must
    # not mark a syntactically valid query invalid (in metadata.py) or break the execute_sql tool call.
    try:
        if visitor.event_literals:
            warnings.extend(
                _warnings_for_unknown_references(
                    "Event",
                    visitor.event_literals,
                    EventDefinition.objects.alias(effective_project_id=effective_project_id_expr()).filter(
                        effective_project_id=team.project_id
                    ),
                )
            )

        if visitor.property_names:
            property_references = [
                reference for reference in visitor.property_names if not _is_dynamic_property(reference.name)
            ]
            if property_references:
                warnings.extend(
                    _warnings_for_unknown_references(
                        "Property",
                        property_references,
                        PropertyDefinition.objects.alias(effective_project_id=effective_project_id_expr()).filter(
                            effective_project_id=team.project_id, type=PropertyDefinition.Type.EVENT
                        ),
                    )
                )
    except DatabaseError:
        logger.warning("Taxonomy validation skipped due to a database error", exc_info=True)
        return []

    return warnings


def _is_event_field(node: ast.Expr) -> bool:
    return isinstance(node, ast.Field) and node.chain in (["event"], ["events", "event"])


def _is_properties_field(node: ast.Expr) -> bool:
    return isinstance(node, ast.Field) and len(node.chain) == 1 and node.chain[0] == "properties"


def _is_dynamic_property(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in DYNAMIC_PROPERTY_PREFIXES)


def _event_literal_from_equality(field_node: ast.Expr, value_node: ast.Expr) -> TaxonomyReference | None:
    if not _is_event_field(field_node):
        return None
    if not isinstance(value_node, ast.Constant) or not isinstance(value_node.value, str):
        return None
    return TaxonomyReference(value_node.value, value_node.start, value_node.end, fix_context="string")


def _string_literals_from_array(node: ast.Expr) -> list[TaxonomyReference]:
    if not isinstance(node, (ast.Array, ast.Tuple)):
        return []

    references: list[TaxonomyReference] = []
    for expr in node.exprs:
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            references.append(TaxonomyReference(expr.value, expr.start, expr.end, fix_context="string"))
    return references


def _warnings_for_unknown_references(
    kind: str, references: list[TaxonomyReference], taxonomy: QuerySet
) -> list[HogQLNotice]:
    if not references:
        return []

    references_by_name: dict[str, TaxonomyReference] = {}
    for reference in references:
        references_by_name.setdefault(reference.name, reference)
    referenced_names = list(references_by_name.keys())

    # Hot path: an indexed `name__in` existence check over the referenced names and their
    # `$`-prefixed forms (usually 2–10 rows). One seek answers both "does this name exist" and
    # "did the caller drop the `$`", so a query whose names are all valid never reads more.
    dollar_prefixed_names = [f"${name}" for name in referenced_names if not name.startswith("$")]
    found_names = set(
        taxonomy.filter(name__in=[*referenced_names, *dollar_prefixed_names]).values_list("name", flat=True)
    )
    unknown_names = [name for name in referenced_names if name not in found_names]
    if not unknown_names:
        return []

    # A project with no definitions yet must not warn on every name. Only ask when nothing was
    # found, because a hit above already proves the taxonomy has rows.
    if not found_names and not taxonomy.exists():
        return []

    suggestions = _suggestions_for(taxonomy, unknown_names[:MAX_SUGGESTED_NAMES], found_names)

    warnings: list[HogQLNotice] = []
    for name in unknown_names:
        reference = references_by_name[name]
        suggestion = suggestions.get(name)
        message = f"{kind} '{name}' was not found in this project taxonomy."
        if suggestion:
            message += f" Did you mean '{suggestion}'?"

        # `fix` is the literal replacement text for the marked range, so it carries the quotes /
        # `properties.` prefix; the message keeps the bare name for readability.
        fix = _build_fix(reference.fix_context, suggestion) if suggestion else None
        warnings.append(HogQLNotice(message=message, start=reference.start, end=reference.end, fix=fix))

    return warnings


def _build_fix(fix_context: FixContext | None, suggestion: str) -> str | None:
    # The fix is spliced verbatim into the query, and the suggested name comes from user-controlled
    # taxonomy — it can contain quotes, backticks, dots or spaces. Escape it for its slot so the
    # quick-fix can never produce broken HogQL (e.g. an event named `o'brien`, or a property with a
    # space). `escape_hogql_identifier` rejects a few names (e.g. containing `%`); offer no fix then.
    try:
        if fix_context == "string":
            return escape_hogql_string(suggestion)
        if fix_context == "property":
            return f"properties.{escape_hogql_identifier(suggestion)}"
    except Exception:
        return None
    return None


def _suggestions_for(taxonomy: QuerySet, names: list[str], found_names: set[str]) -> dict[str, str]:
    """Map the names that earn a suggestion to the name suggested for each.

    A name whose `$`-prefixed form is already in `found_names` needs no further read: the existence
    check above proved that name exists. The rest share one candidate read, because a read per name
    would cost a round trip per name.
    """
    suggestions: dict[str, str] = {}
    unresolved: list[str] = []
    for name in names:
        dollar_prefixed = f"${name}"
        if dollar_prefixed in found_names:
            suggestions[name] = dollar_prefixed
        else:
            unresolved.append(name)

    if not unresolved:
        return suggestions

    candidates = _candidate_names(taxonomy, unresolved)
    for name in unresolved:
        closest = _closest_name(name, candidates)
        if closest:
            suggestions[name] = closest

    return suggestions


def _candidate_names(taxonomy: QuerySet, names: list[str]) -> list[str]:
    """Read the project's definition names that can still reach the similarity cutoff.

    The read is scoped to the project, so Postgres seeks it in `posthog_propdef_proj_uniq` /
    `event_definition_proj_uniq` and stays inside the project's rows. A trigram match on `name`
    cannot do that: the only index that answers the pg_trgm `%` operator is a GIN index on `name`
    alone, so Postgres matches and ranks the name across every team first, then applies the project
    scope to the result.

    A candidate scores `2 * matching_characters / (len(name) + len(candidate))`, and the match count
    cannot exceed the shorter of the two. A candidate outside the length band that follows can
    therefore never reach the cutoff, so Postgres drops it before it reaches Python.

    A name longer than the `name` column can never equal a definition, so an oversized literal is
    dropped rather than compared.
    """
    comparable = [name for name in names if len(name) <= MAX_SUGGESTION_INPUT_LENGTH]
    if not comparable:
        return []

    span = 2 / SIMILARITY_CUTOFF - 1
    shortest = ceil(min(len(name) for name in comparable) / span)
    longest = floor(max(len(name) for name in comparable) * span)

    return list(
        taxonomy.alias(name_length=Length("name"))
        .filter(name_length__gte=shortest, name_length__lte=longest)
        .order_by("name")
        .values_list("name", flat=True)[:SUGGESTION_CANDIDATE_LIMIT]
    )


def _closest_name(name: str, candidates: list[str]) -> str | None:
    matches = get_close_matches(name, candidates, n=1, cutoff=SIMILARITY_CUTOFF)
    return matches[0] if matches else None
