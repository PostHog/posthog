"""Rules a Signals scout's event definition writes must clear, on top of the scopes its token carries.

A person grants one scout `event_definition:write` from the scout's settings, and that grant is
deliberately narrower than the scope object: it lets a scout change the tags on event definitions
and nothing else. The scope object also covers creating, describing, verifying, hiding, and
deleting a definition, its owner and schema enforcement, and the property groups and media previews
attached to it. Delete is permanent and takes the definition's description, tags, and owner with
it, and a schema change can make ingestion reject events, so none of these fit an unattended agent.
One scope object covers the whole surface, so the narrowing is enforced here.

Every rule applies to scout sandbox callers alone (`is_scout_sandbox_request`), so a person working
in the app or a personal API key sees no change.
"""

from collections.abc import Mapping
from typing import Any

from rest_framework.exceptions import PermissionDenied

from posthog.api.tagged_item import BulkUpdateTagsAction

TAGS_ONLY = (
    "Scouts can change only the tags of an event definition. Say in your report which other change a "
    "person should make."
)

BULK_SET_REFUSED = (
    "Scouts cannot set tags in bulk, because `set` removes the tags people added to every listed "
    "event definition. Use `add` or `remove`."
)

_UPDATE_ACTIONS = frozenset({"update", "partial_update"})


def refuse_scout_taxonomy_write(is_scout_caller: bool) -> None:
    """Refuse a scout's write to a view that shares the `event_definition` scope but has no tags.

    These are event schemas, schema property groups, and media previews. A schema decides which
    properties an event must carry, and an event definition in reject mode drops events that miss
    one at ingestion.
    """
    if is_scout_caller:
        raise PermissionDenied(TAGS_ONLY)


def check_scout_event_definition_write(is_scout_caller: bool, *, action: str | None, data: Any) -> None:
    """Refuse a scout's event definition write unless it changes tags and nothing else.

    An update may carry `tags` alone. The field replaces the whole list, so the scout has to read
    the current tags and send them back with its change. A bulk change may add or remove tags but
    not set them, because one `set` call replaces the tags on every listed definition.
    """
    if not is_scout_caller:
        return
    if action in _UPDATE_ACTIONS and isinstance(data, Mapping) and set(data) <= {"tags"}:
        return
    if action == "bulk_update_tags" and isinstance(data, Mapping):
        if data.get("action") == BulkUpdateTagsAction.SET:
            raise PermissionDenied(BULK_SET_REFUSED)
        return
    raise PermissionDenied(TAGS_ONLY)
