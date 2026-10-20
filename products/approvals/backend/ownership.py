from typing import Optional

# A recorded classification meaning "nothing owned this resource". It is distinct from NULL,
# which means no classification was recorded at all: a request created before the column
# existed, or an action that does not classify ownership. Those must still apply.
OWNER_KIND_UNOWNED = "unowned"


def owner_kind_changed(recorded: Optional[str], current: Optional[str]) -> bool:
    """Whether the owner recorded when a change request was created still holds.

    An absent classification on either side is not a change. That keeps requests created
    before the column existed applying exactly as they did, and leaves actions that do not
    classify ownership unaffected.
    """
    if recorded is None or current is None:
        return False
    return recorded != current
