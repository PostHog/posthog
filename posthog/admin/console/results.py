import json
import secrets
import dataclasses
from enum import StrEnum
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.cache import caches
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse

from cryptography.fernet import Fernet, InvalidToken

from posthog.admin.console.tools import (
    Cell,
    GroupRow,
    Link,
    Links,
    Live,
    Notice,
    Output,
    Page,
    Paging,
    Row,
    Secret,
    Stat,
    Stats,
    Table,
)
from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.admin.console.views import OperationTarget

RESULT_TTL_SECONDS = 60
CACHE_ALIAS = "admin_console_results"
KEY_PREFIX = "admin_console_result"
KEY_COOKIE = "admin_console_result_key"


@frozen
class OperationResult:
    actor_id: int
    operation_label: str
    target: "OperationTarget"
    page: Page

    def __post_init__(self) -> None:
        if any(isinstance(block, Live) for block in self.page.blocks):
            raise ValueError("A result page shows what happened once. Put live blocks on the tool page instead.")


class ResultState(StrEnum):
    SHOWN = "shown"
    # Already shown, expired, or stored by another staff member.
    GONE = "gone"
    # The browser sent no key or a wrong one. The entry stays, so the browser that ran the operation can open it.
    KEY_MISSING = "key-missing"
    # Stored in a format this version cannot read, for example by a pod of the previous deploy.
    UNREADABLE = "unreadable"


@frozen
class ResultRead:
    state: ResultState
    result: OperationResult | None = None


class ResultCodec:
    """Turns a result into JSON and back, so the cache can hold it encrypted. Decoding builds only the console
    types listed here, never an arbitrary object."""

    @staticmethod
    def _types() -> dict[str, type]:
        from posthog.admin.console.records import RecordLink  # noqa: PLC0415
        from posthog.admin.console.views import OperationTarget  # noqa: PLC0415

        types = (OperationResult, OperationTarget, RecordLink, Page, Notice, Table, Row, GroupRow, Cell, Paging)
        return {cls.__name__: cls for cls in (*types, Output, Secret, Stats, Stat, Links, Link)}

    @classmethod
    def _encode(cls, value: object) -> object:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            fields = {field.name: cls._encode(getattr(value, field.name)) for field in dataclasses.fields(value)}
            return {"__type__": type(value).__name__, **fields}
        if isinstance(value, tuple):
            return [cls._encode(item) for item in value]
        return value

    @classmethod
    def _decode(cls, value: object, types: dict[str, type]) -> object:
        # Every sequence in a console block is a tuple, and JSON brings each one back as a list.
        if isinstance(value, list):
            return tuple(cls._decode(item, types) for item in value)
        if isinstance(value, dict):
            fields = {name: cls._decode(item, types) for name, item in value.items() if name != "__type__"}
            return types[value["__type__"]](**fields)
        return value

    @classmethod
    def dumps(cls, result: OperationResult) -> bytes:
        return json.dumps(cls._encode(result)).encode()

    @classmethod
    def loads(cls, data: bytes) -> object:
        return cls._decode(json.loads(data), cls._types())


class OperationResults:
    """Hands an operation's result page from the POST that ran it to the GET that shows it, once.

    The POST stores the page under an id nobody can guess and redirects to it, so a reload of the result
    asks for the page again and never runs the operation again. The first read deletes the entry, so a
    `Secret` block is shown once and is not kept. A later read says the result was already shown.

    The cache holds only ciphertext. Each result has its own key, which goes to the browser in a cookie
    scoped to the result's path, so the cache entry alone or the cookie alone reveals nothing.
    """

    @staticmethod
    def _cache_key(result_id: str) -> str:
        return f"{KEY_PREFIX}:{result_id}"

    @staticmethod
    def _cookie_path(result_id: str) -> str:
        return reverse("admin_console_result", kwargs={"result_id": result_id})

    @classmethod
    def redirect_to(cls, result: OperationResult) -> HttpResponse:
        """Stores the result and answers with a redirect to it that carries its key."""
        result_id = secrets.token_urlsafe(32)
        key = Fernet.generate_key()
        ciphertext = Fernet(key).encrypt(ResultCodec.dumps(result))
        caches[CACHE_ALIAS].set(cls._cache_key(result_id), (result.actor_id, ciphertext), timeout=RESULT_TTL_SECONDS)
        response = HttpResponseRedirect(cls._cookie_path(result_id))
        response.set_cookie(
            KEY_COOKIE,
            key.decode(),
            max_age=RESULT_TTL_SECONDS,
            path=cls._cookie_path(result_id),
            secure=settings.SESSION_COOKIE_SECURE,
            httponly=True,
            samesite="Strict",
        )
        return response

    @classmethod
    def take(cls, request: HttpRequest, result_id: str) -> ResultRead:
        cache = caches[CACHE_ALIAS]
        cache_key = cls._cache_key(result_id)
        entry = cache.get(cache_key)
        if not isinstance(entry, tuple) or entry[0] != request.user.pk:
            return ResultRead(state=ResultState.GONE)
        try:
            plaintext = Fernet(request.COOKIES.get(KEY_COOKIE, "")).decrypt(entry[1])
        except (InvalidToken, ValueError):
            return ResultRead(state=ResultState.KEY_MISSING)
        try:
            result = ResultCodec.loads(plaintext)
        except (KeyError, TypeError, ValueError):
            result = None
        # The delete decides who shows it: when two requests read the entry at once, only the one whose
        # delete removed it shows the page.
        if not cache.delete(cache_key):
            return ResultRead(state=ResultState.GONE)
        if not isinstance(result, OperationResult):
            return ResultRead(state=ResultState.UNREADABLE)
        return ResultRead(state=ResultState.SHOWN, result=result)

    @classmethod
    def forget_key(cls, response: HttpResponse, result_id: str) -> HttpResponse:
        """Clears the key cookie once the entry is gone, so it does not outlive the result."""
        response.delete_cookie(KEY_COOKIE, path=cls._cookie_path(result_id), samesite="Strict")
        return response
