"""Extraction of realtime-cohort filter definitions from cohort models.

Shared by the person-properties backfill command and the merge reconciliation workflow so
the two can't drift on what counts as a usable realtime person-property filter.
"""

from posthog.temporal.messaging.types import PersonPropertyFilter

from products.cohorts.backend.models.cohort import Cohort


def extract_person_property_filters(cohort: Cohort) -> list[PersonPropertyFilter]:
    """
    Extract person property filters from a realtime cohort.

    Recursively traverses the filter tree to find all person property filters
    with conditionHash and bytecode.

    Returns a list of PersonPropertyFilter objects suitable for passing to the workflow.
    """
    filters: list[PersonPropertyFilter] = []

    if not cohort.filters:
        return filters

    properties = cohort.filters.get("properties")
    if not properties:
        return filters

    def traverse_filter_tree(node):
        """Recursively traverse the filter tree to find person property filters."""
        if not isinstance(node, dict):
            return

        # Check if this is a group node (AND/OR)
        node_type = node.get("type")
        if node_type in ("AND", "OR"):
            # Recursively process children
            for child in node.get("values", []):
                traverse_filter_tree(child)
            return

        # This is a leaf node - check if it's a person property filter
        if node_type != "person":
            return

        condition_hash = node.get("conditionHash")
        bytecode = node.get("bytecode")
        property_key = node.get("key")

        # Skip if missing required fields or if they're empty
        if not condition_hash or not bytecode or not property_key:
            return

        filters.append(
            PersonPropertyFilter(
                condition_hash=condition_hash,
                bytecode=bytecode,
                cohort_ids=[],  # Will be populated during deduplication
                property_key=property_key,
            )
        )

    # Start traversal from the root properties node
    traverse_filter_tree(properties)

    return filters


def extract_deduplicated_person_property_filters(cohorts: list[Cohort]) -> list[PersonPropertyFilter]:
    """Extract person-property filters across cohorts, deduplicated by condition_hash.

    Each returned filter carries the sorted list of cohort IDs that use its condition;
    ordering is by condition_hash so callers get a deterministic filter list.
    """
    condition_map: dict[str, PersonPropertyFilter] = {}
    for cohort in cohorts:
        for extracted in extract_person_property_filters(cohort):
            existing = condition_map.get(extracted.condition_hash)
            if existing is None:
                extracted.cohort_ids = [cohort.id]
                condition_map[extracted.condition_hash] = extracted
            elif cohort.id not in existing.cohort_ids:
                existing.cohort_ids.append(cohort.id)
    for pp_filter in condition_map.values():
        pp_filter.cohort_ids.sort()
    return [condition_map[condition_hash] for condition_hash in sorted(condition_map)]
