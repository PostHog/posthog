import re

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.models.element.element import wanted_attribute_entries

_ATTRIBUTE_KEY_CHARS = r"[a-zA-Z0-9_:.\-]"
_ATTRIBUTE_PAIR_PATTERN = rf'attr__{_ATTRIBUTE_KEY_CHARS}+="(?:[^"\\]|\\.)*"'
_KEPT_ATTRIBUTE_SENTINEL = "\x01"

_NORMALIZED_CHAIN_SQL = (
    "replaceRegexpAll(replaceRegexpAll(replaceRegexpAll("
    "elements_chain, {protect}, {protect_with}), {strip}, ''), {restore}, {restore_with})"
)


def normalized_elements_chain_expr(wanted_data_attributes: list[str]) -> ast.Expr:
    entries = wanted_attribute_entries(wanted_data_attributes)
    if not entries:
        return ast.Field(chain=["elements_chain"])

    kept = "|".join(re.escape(entry).replace(r"\*", f"{_ATTRIBUTE_KEY_CHARS}*") for entry in entries)
    return parse_expr(
        _NORMALIZED_CHAIN_SQL,
        placeholders={
            "protect": ast.Constant(value=rf'attr__({kept})="'),
            "protect_with": ast.Constant(value=_KEPT_ATTRIBUTE_SENTINEL + r'\1="'),
            "strip": ast.Constant(value=_ATTRIBUTE_PAIR_PATTERN),
            "restore": ast.Constant(value=_KEPT_ATTRIBUTE_SENTINEL),
            "restore_with": ast.Constant(value="attr__"),
        },
    )
