"""Callable discriminator for the AnyPropertyFilter union in the generated posthog/schema.py.

bin/patch-schema-property-filter-discriminator.py rewrites every inlined property-filter
union in posthog/schema.py into a tagged union discriminated by this function. A callable
(rather than ``Field(discriminator="type")``) is required because the union must keep
accepting payloads a plain tag lookup would reject:

- filters saved before ``type`` was consistently written omit it entirely,
- ``{}`` rows (the UI's "new filter" placeholder) must resolve to EmptyPropertyFilter,
- LogPropertyFilter/SpanPropertyFilter accept several ``type`` values each (StrEnum tags),
- PropertyGroupFilterValue recursively unions with the filters but is tagged AND/OR.

Keep this module dependency-free: posthog/schema.py imports it, so it must not import
posthog.* (or anything heavy) back.
"""

PROPERTY_FILTER_TYPE_CANONICALIZATION: dict[str, str] = {
    "log_attribute": "log",
    "log_resource_attribute": "log",
    "span_attribute": "span",
    "span_resource_attribute": "span",
    # PropertyGroupFilterValue's tag namespace (FilterLogicalOperator) — only reachable at
    # sites whose union includes it (e.g. PropertyGroupFilterValue.values).
    "AND": "property_group",
    "OR": "property_group",
}


def property_filter_discriminator(value: object) -> str:
    """Return the union tag for a property-filter dict or model instance."""
    if isinstance(value, dict):
        raw = value.get("type")
        has_key = "key" in value
    else:
        raw = getattr(value, "type", None)
        has_key = hasattr(value, "key")
    if raw is None:
        # Pre-discriminator smart-union behavior: type-less filters validated as
        # EventPropertyFilter via its default, and bare `{}` as EmptyPropertyFilter.
        return "event" if has_key else "empty"
    raw_str = str(raw)  # StrEnum tags (log/span variants, AND/OR) stringify to their value
    return PROPERTY_FILTER_TYPE_CANONICALIZATION.get(raw_str, raw_str)
