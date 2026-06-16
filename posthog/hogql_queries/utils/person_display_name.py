import re

VALID_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def person_display_name_property_exprs(property_keys: list[str], prefix: str) -> list[str]:
    """Build per-property HogQL expressions for a person display-name coalesce.

    Each property access is wrapped in nullIf(toString(...), '') so empty-string property
    values become NULL and coalesce falls through to the next property, matching the
    Python/JS truthiness behavior (only "" is falsy).

    `prefix` is the trusted table/column prefix, e.g. "person.properties", "properties",
    or "__person_lookup.properties". property_keys come from admin-only team config.
    """
    exprs: list[str] = []
    for key in property_keys:
        if VALID_IDENTIFIER_PATTERN.match(key):
            exprs.append(f"nullIf(toString({prefix}.{key}), '')")
        else:
            exprs.append(f"nullIf(toString({prefix}.`{key}`), '')")
    return exprs
