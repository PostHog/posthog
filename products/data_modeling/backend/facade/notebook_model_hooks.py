from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, BinaryIO
from uuid import UUID

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models import User


@frozen
class NotebookModelExecutor:
    prepare: Callable[[int, UUID, str, str, int, UUID], list[str] | None]
    open_output: Callable[[int, UUID, UUID, int], AbstractContextManager[tuple[BinaryIO, int]]]
    authorize: Callable[[int, UUID, User], User]
    stop: Callable[[int, UUID], None]


_factory: Callable[[], NotebookModelExecutor] | None = None


def register_notebook_model_executor(factory: Callable[[], NotebookModelExecutor]) -> None:
    global _factory
    _factory = factory


def notebook_model_executor() -> NotebookModelExecutor:
    if _factory is None:
        raise RuntimeError("The notebook model executor is unavailable.")
    return _factory()
