"""Deny-list of property keys that should not be ingested into the
property_values autocomplete table.

Two sources, combined into a single frozenset:

1. Taxonomy flags from CORE_FILTER_DEFINITIONS_BY_GROUP. Anything already marked
   `system`, `ignored_in_assistant`, or `used_for_debug` is by definition not
   shown to users in the filter UI, so storing its values for autocomplete is
   wasted work.
2. Empirically high-cardinality keys observed during the property_values
   rollout that are not yet flagged in the taxonomy. Promote these into the
   taxonomy with the appropriate flag and remove from the supplementary set
   when convenient.

Used by the WarpStream Bento pipeline to drop fan-out for these keys at the
source, and by the autocomplete API to avoid serving stored values for them.
"""

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

_DENY_FROM_TAXONOMY: frozenset[str] = frozenset(
    key
    for group in CORE_FILTER_DEFINITIONS_BY_GROUP.values()
    for key, meta in group.items()
    if meta.get("system") or meta.get("ignored_in_assistant") or meta.get("used_for_debug")
)

# Keys not yet flagged in the taxonomy but observed to have unbounded cardinality
# (UUIDs, free-text blobs) or no autocomplete utility (numeric coordinates,
# high-resolution timestamps stored as date-typed strings).
_DENY_SUPPLEMENTARY: frozenset[str] = frozenset(
    {
        "$creator_event_uuid",
        "$initial_geoip_longitude",
        "$initial_geoip_latitude",
        "$geoip_longitude",
        "$geoip_latitude",
        "$survey_last_seen_date",
    }
)

PROPERTY_VALUES_DENY: frozenset[str] = _DENY_FROM_TAXONOMY | _DENY_SUPPLEMENTARY
