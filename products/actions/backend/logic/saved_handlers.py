"""The handlers other products register to hear about action saves.

Kept free of model imports, so the action model's own post_save receiver can call into it.
"""

from collections.abc import Callable

from ..facade.contracts import ActionSaved

ActionSavedHandler = Callable[[ActionSaved], None]

_handlers: dict[str, ActionSavedHandler] = {}


def register(handler: ActionSavedHandler, *, dispatch_uid: str) -> None:
    # Keyed like a Django receiver's dispatch_uid, so a module imported twice registers once.
    _handlers.setdefault(dispatch_uid, handler)


def dispatch(event: ActionSaved) -> None:
    for handler in list(_handlers.values()):
        handler(event)
