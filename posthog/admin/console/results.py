import secrets
from typing import TYPE_CHECKING

from django.core.cache import caches
from django.http import HttpRequest

from posthog.admin.console.tools import Live, Page
from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.admin.console.views import OperationTarget

RESULT_TTL_SECONDS = 60
CACHE_ALIAS = "admin_console_results"
KEY_PREFIX = "admin_console_result"


@frozen
class OperationResult:
    actor_id: int
    operation_label: str
    target: "OperationTarget"
    page: Page

    def __post_init__(self) -> None:
        if any(isinstance(block, Live) for block in self.page.blocks):
            raise ValueError("A result page shows what happened once. Put live blocks on the tool page instead.")


class OperationResults:
    """Hands an operation's result page from the POST that ran it to the GET that shows it, once.

    The POST stores the page under an id nobody can guess and redirects to it, so a reload of the result
    asks for the page again and never runs the operation again. The first read deletes the entry, so a
    `Secret` block is shown once and is not kept. A later read says the result was already shown.
    """

    @staticmethod
    def _key(result_id: str) -> str:
        return f"{KEY_PREFIX}:{result_id}"

    @classmethod
    def store(cls, result: OperationResult) -> str:
        result_id = secrets.token_urlsafe(32)
        caches[CACHE_ALIAS].set(cls._key(result_id), result, timeout=RESULT_TTL_SECONDS)
        return result_id

    @classmethod
    def take(cls, request: HttpRequest, result_id: str) -> OperationResult | None:
        """The result, or None when it was already shown, expired, or belongs to another staff member."""
        cache = caches[CACHE_ALIAS]
        key = cls._key(result_id)
        result = cache.get(key)
        if not isinstance(result, OperationResult) or result.actor_id != request.user.pk:
            return None
        # The delete decides who shows it: when two requests read the entry at once, only the one whose
        # delete removed it shows the page.
        if not cache.delete(key):
            return None
        return result
