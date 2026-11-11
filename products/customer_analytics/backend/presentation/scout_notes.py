"""Rules for the account notes a Signals scout writes, on top of the `account_note:write` scope its token carries.

A person grants one scout `account_note:write` from the scout's settings. A scout acts as the person who owns its
config, so without a mark of its own a scout's note looks exactly like that person wrote it. Every note a scout writes
through the account notes API is therefore tagged `scout`, plus `scout-<skill name>` when the run's skill is known.
The tags are added here, server-side, so a scout cannot leave its own off, and its name comes from the token rather
than the request. A scout can retag only a note that already carries `scout`, and a retag keeps the note's existing
`scout` tags, so a scout cannot remove them later. Without that check, a scout retag of a note a person wrote would
mark it `scout`, which tells every other scout to skip it as a scout write-up, and would drop the person's tags. A
scout can still add other tags, another scout's name included, so read attribution from the tag the server adds, not
from the absence of others. A scout cannot delete a note through this API, because the note may be the only record of
what a person found.

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

RETAG_REFUSED = (
    "Scouts can only retag account notes a scout wrote. Say in your report which tags a person should change."
)


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


def _is_scout_tag(tag: str) -> bool:
    return tag == SCOUT_NOTE_TAG or tag.startswith(f"{SCOUT_NOTE_TAG}-")


def with_scout_tags(is_scout_caller: bool, tags: Iterable[str]) -> list[str]:
    """The tags for a new note: a scout's topic tags plus its scout tags, or a person's tags unchanged."""
    if not is_scout_caller:
        return list(tags)
    return [*tags, *scout_note_tags()]


def scout_retag(tags: Iterable[str], existing_tags: Iterable[str]) -> list[str]:
    """The tags to write when a scout retags a note.

    The note must already carry `scout`. The scout's topic tags replace the note's other tags, and the note's existing
    `scout` tags stay.
    """
    kept = [tag for tag in existing_tags if _is_scout_tag(tag)]
    if SCOUT_NOTE_TAG not in kept:
        raise PermissionDenied(RETAG_REFUSED)
    return [*(tag for tag in tags if not _is_scout_tag(tag)), *kept]


def refuse_scout_note_delete(is_scout_caller: bool) -> None:
    if is_scout_caller:
        raise PermissionDenied(DELETE_REFUSED)
