# mypy: disable-error-code="assignment"

from __future__ import annotations

from typing import Any

from pydantic import RootModel


class SchemaRoot(RootModel[Any]):
    root: Any
