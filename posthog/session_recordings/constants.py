"""
Constants for session recording functionality.
"""

# Extra fields needed for session summary functionality
EXTRA_SUMMARY_EVENT_FIELDS = [
    "elements_chain_ids",
    "elements_chain",
    "properties.$exception_types",
    "properties.$exception_sources",
    "properties.$exception_values",
    "properties.$exception_fingerprint_record",
    "properties.$exception_functions",
    "uuid",
]

# Columns that are useful to building context or/and filtering, but would be excessive for the LLM
COLUMNS_TO_REMOVE_FROM_LLM_CONTEXT = [
    "elements_chain",
    "$exception_sources",
    "$exception_fingerprint_record",
    "$exception_functions",
]

# How many events to fetch by default
DEFAULT_TOTAL_EVENTS_PER_QUERY = 10000

# Maximum number of events to fetch per query
MAX_TOTAL_EVENTS_PER_QUERY = 50000
