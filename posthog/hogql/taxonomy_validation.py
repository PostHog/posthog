from dataclasses import dataclass
from difflib import get_close_matches
from logging import getLogger
from typing import Literal

from django.contrib.postgres.search import TrigramSimilarity
from django.db import DatabaseError
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When
from django.db.models.functions import Greatest

from posthog.schema import HogQLNotice

from posthog.hogql import ast
from posthog.hogql.escape_sql import escape_hogql_identifier, escape_hogql_string
from posthog.hogql.visitor import TraversingVisitor

from posthog.models import EventDefinition, PropertyDefinition, Team
from posthog.taxonomy.taxonomy import virtual_property_names

from products.event_definitions.backend.models.property_definition import effective_project_id_expr

logger = getLogger(__name__)

# Virtual event properties (e.g. `$virt_traffic_type`, `$virt_is_bot`) are computed at query time from
# event data and never persisted as PropertyDefinition rows, so a lookup against the table would flag
# them as unknown. `read_taxonomy` reads the same source, so the two tools stay in agreement.
VIRTUAL_EVENT_PROPERTY_NAMES = virtual_property_names("event_properties")

# How a suggested name is rendered back into the marked range for a one-click fix:
# `string` → a quoted, escaped string literal (event `=`/`IN` values, `properties['key']` keys);
# `property` → a `properties.<identifier>` field. Both escape the suggestion (see `_build_fix`).
FixContext = Literal["string", "property"]

# How many similar names the suggestion lookup reads per typed name. Postgres ranks candidates by
# trigram similarity, so the best match is in the first rows and difflib does not need every name.
SUGGESTION_CANDIDATE_LIMIT = 20

# The `name` column of both definition models is `CharField(max_length=400)`.
MAX_SUGGESTION_INPUT_LENGTH = 400

# How many unknown names in one query get a suggestion. One lookup covers the whole batch, but
# pg_trgm compares every name in it, and a caller controls how many unknown names one query carries.
# Names past this cap still warn, only without "Did you mean".
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
    # `properties['name']` bracket access reads the raw JSON blob directly; `properties.name` dot access is
    # the form the resolver remaps onto a virtual top-level field for `$virt` names. Recording the form lets
    # the validator exempt a virtual name only for the dot access that actually reaches the computed value.
    bracket_access: bool = False


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
                TaxonomyReference(
                    node.property.value,
                    node.property.start,
                    node.property.end,
                    fix_context="string",
                    bracket_access=True,
                )
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
                reference for reference in visitor.property_names if not _is_known_computed_property(reference)
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


def _is_known_computed_property(reference: TaxonomyReference) -> bool:
    # Properties that legitimately never appear in PropertyDefinition and so must not be flagged as unknown.
    # Dynamic id-encoding prefixes (feature flags, survey ids) are real JSON keys read the same way through
    # dot or bracket access, so they are always exempt. A virtual property is computed at query time, and the
    # resolver only remaps the `properties.<name>` dot form onto the computed top-level field; bracket access
    # (`properties['<name>']`) reads the raw JSON blob, where the virtual value is never stored, so it returns
    # an empty value and must still warn. A typo'd virtual name (e.g. `$virt_trafic_type`) is not in the set,
    # so it also still warns.
    name = reference.name
    if any(name.startswith(prefix) for prefix in DYNAMIC_PROPERTY_PREFIXES):
        return True
    return name in VIRTUAL_EVENT_PROPERTY_NAMES and not reference.bracket_access


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

    # Hot path: an indexed `name__in` existence check over only the referenced names (usually 1–5).
    # When every name is valid we never load more.
    found_names = set(taxonomy.filter(name__in=referenced_names).values_list("name", flat=True))
    unknown_names = [name for name in referenced_names if name not in found_names]
    if not unknown_names:
        return []

    # A project with no definitions yet must not warn on every name. Only ask when nothing was
    # found, because a hit above already proves the taxonomy has rows.
    if not found_names and not taxonomy.exists():
        return []

    suggestions = _suggestions_for(taxonomy, unknown_names[:MAX_SUGGESTED_NAMES])

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


def _suggestions_for(taxonomy: QuerySet, names: list[str]) -> dict[str, str]:
    """Map the names that earn a suggestion to the name suggested for each.

    One candidate read covers the whole batch. A read per name would cost a round trip per name, and
    a typical project holds a few hundred definitions, where those round trips cost more than the
    comparison they save.
    """
    candidates = _similar_names(taxonomy, names)
    if not candidates:
        return {}

    candidate_set = set(candidates)
    suggestions: dict[str, str] = {}
    for name in names:
        dollar_prefixed = f"${name}"
        if not name.startswith("$") and dollar_prefixed in candidate_set:
            suggestions[name] = dollar_prefixed
            continue

        closest = _closest_name(name, candidates)
        if closest:
            suggestions[name] = closest

    return suggestions


def _similar_names(taxonomy: QuerySet, names: list[str]) -> list[str]:
    """Read the names most similar to any of `names`, ranked and capped by Postgres.

    `name__trigram_similar` is the pg_trgm `%` operator, which the GIN trigram indexes
    `index_event_definition_name` and `index_property_definition_name` answer directly. Postgres
    still intersects that match with the project scope, so this call is bounded by what it returns,
    not by what it reads.

    The `$`-prefixed form of each name is matched exactly as well, and sorts ahead of the ranked
    candidates. A caller who typed a name without its `$` therefore keeps that suggestion however
    many other candidates the batch pulls in.

    A name longer than the `name` column can never equal a definition, and pg_trgm cost grows with
    the input, so an oversized literal is dropped rather than compared.
    """
    comparable = [name for name in names if len(name) <= MAX_SUGGESTION_INPUT_LENGTH]
    if not comparable:
        return []

    dollar_prefixed = [f"${name}" for name in comparable if not name.startswith("$")]

    matches = Q(name__in=dollar_prefixed) if dollar_prefixed else Q()
    for name in comparable:
        matches |= Q(name__trigram_similar=name)

    similarities = [TrigramSimilarity("name", name) for name in comparable]
    ranked = taxonomy.filter(matches).annotate(
        # `Greatest` needs two expressions, and one unknown name is the common case.
        name_similarity=Greatest(*similarities) if len(similarities) > 1 else similarities[0]
    )

    ordering = ["-name_similarity", "name"]
    if dollar_prefixed:
        ranked = ranked.annotate(
            name_is_dollar_prefixed=Case(
                When(name__in=dollar_prefixed, then=Value(1)), default=Value(0), output_field=IntegerField()
            )
        )
        ordering.insert(0, "-name_is_dollar_prefixed")

    return list(
        ranked.order_by(*ordering).values_list("name", flat=True)[: SUGGESTION_CANDIDATE_LIMIT * len(comparable)]
    )


def _closest_name(name: str, candidates: list[str]) -> str | None:
    # pg_trgm selects candidates at the server's `pg_trgm.similarity_threshold` (0.3 by default),
    # which is loose enough to return names a reader would not accept as a typo. difflib makes the
    # final call at a stricter cutoff, so a suggestion needs both measures to agree.
    matches = get_close_matches(name, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None
