from collections.abc import Callable

from django.db import transaction

SqlReferenceRewriteHandler = Callable[[int, str, str, object | None], int]

_handlers: dict[str, SqlReferenceRewriteHandler] = {}


def register_sql_reference_rewrite_handler(name: str, handler: SqlReferenceRewriteHandler) -> None:
    """Register a product-owned handler for SQL references to a renamed saved query."""
    _handlers[name] = handler


@transaction.atomic
def rewrite_registered_sql_references(
    team_id: int, old_name: str, new_name: str, user_access_control: object | None
) -> dict[str, int]:
    """Run registered product handlers inside the saved-query rename transaction."""
    return {name: handler(team_id, old_name, new_name, user_access_control) for name, handler in _handlers.items()}
