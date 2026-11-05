"""Rules for the account notes a Signals scout writes, on top of the `account_note:write` scope its token carries.

A person grants one scout `account_note:write` from the scout's settings. A scout acts as the person who owns its
config, so without a mark of its own a scout's note looks exactly like that person wrote it. Every note a scout writes
or retags through the account notes API is therefore tagged `scout`, plus `scout-<skill name>` when the run's skill is
known. The tags are added here, server-side, so a scout cannot leave its own off or remove them later, and its name
comes from the token rather than the request. A scout can still add other tags, another scout's name included, so read
attribution from the tag the server adds, not from the absence of others. A scout cannot delete a note through this
API, because the note may be the only record of what a person found.

These rules cover the account notes endpoints only. An account note is also a notebook, so a scout holding
`notebook:write` (granted by default) can still edit one or soft-delete it, recoverably, through the notebooks API.

Every rule applies to scout sandbox callers alone (`is_scout_sandbox_request`), so a person working in the app or a
personal API key sees no change, and a person can still remove the tags.
"""

from collections.abc import Iterable

from rest_framework.exceptions import PermissionDenied

from posthog.models.activity_logging.utils import SCOUT_CLIENT_PREFIX, activity_storage

SCOUT_NOTE_TAG = "scout"

# Built-in scouts' skill names all start with this, which would otherwise read `scout-signals-scout-...`.
BUILT_IN_SCOUT_SKILL_PREFIX = "signals-scout-"

DELETE_REFUSED = "Scouts cannot delete account notes. Say in your report which note a person should remove."


def scout_note_tags() -> list[str]:
    """`scout`, plus `scout-<skill name>` when the token's task resolves to a scout run.

    The skill comes from the activity client the scout sandbox token's authenticator resolved from the task the
    token was minted for, a binding written server-side, so a scout cannot choose the name it is tagged with.
    """
    tags = [SCOUT_NOTE_TAG]
    client = activity_storage.get_client()
    if client and client.startswith(SCOUT_CLIENT_PREFIX):
        skill_name = client[len(SCOUT_CLIENT_PREFIX) :].strip().removeprefix(BUILT_IN_SCOUT_SKILL_PREFIX)
        if skill_name:
            tags.append(f"{SCOUT_NOTE_TAG}-{skill_name}")
    return tags


def with_scout_tags(is_scout_caller: bool, tags: Iterable[str] | None) -> list[str] | None:
    """The tags to write: a scout's own topic tags plus its scout tags, or a person's tags unchanged.

    `None` means the request leaves the tags untouched, for a scout as for a person: replacing them with the scout
    tags alone would wipe the note's topic tags.
    """
    if tags is None:
        return None
    if not is_scout_caller:
        return list(tags)
    return [*tags, *scout_note_tags()]


def refuse_scout_note_delete(is_scout_caller: bool) -> None:
    if is_scout_caller:
        raise PermissionDenied(DELETE_REFUSED)
