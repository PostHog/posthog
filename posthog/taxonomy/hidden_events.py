from collections import Counter
from collections.abc import Iterable

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

EVENTS_HIDDEN_IN_QUERY_BUILDERS: frozenset[str] = frozenset(
    name
    for name, defn in CORE_FILTER_DEFINITIONS_BY_GROUP.get("events", {}).items()
    if defn.get("hidden_in_query_builders")
)

HIDDEN_EVENT_REASON = (
    "PostHog still collects this event, but its data is moving, so anything new built on it would stop working. "
    "To see how a flag is used, open the flag and check its Usage tab."
)


def added_hidden_event(new_event_names: Iterable[object], existing_event_names: Iterable[object]) -> str | None:
    """The hidden event that a save adds a reference to, or None.

    A save may keep, edit or drop the references that the stored object already has. Only a count above
    the stored count is an addition.
    """
    new = Counter(name for name in new_event_names if name in EVENTS_HIDDEN_IN_QUERY_BUILDERS)
    existing = Counter(name for name in existing_event_names if name in EVENTS_HIDDEN_IN_QUERY_BUILDERS)
    added = new - existing
    return str(next(iter(added))) if added else None
