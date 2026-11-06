# Test cases for tuple-return-prefer-dataclass.
# ruff: noqa
from typing import Optional, Tuple


# Two elements sharing a type are swappable at the call site
# ruleid: tuple-return-prefer-dataclass
def get_range() -> tuple[int, int]:
    return 0, 1


# Legacy typing.Tuple spelling counts too
# ruleid: tuple-return-prefer-dataclass
def get_bounds() -> Tuple[float, float]:
    return 0.0, 1.0


# A same-type pair wrapped in Optional is still swappable
# ruleid: tuple-return-prefer-dataclass
def maybe_range() -> Optional[tuple[str, str]]:
    return None


# ruleid: tuple-return-prefer-dataclass
def union_range() -> tuple[int, int] | None:
    return None


# Nested generics still count as the same type
# ruleid: tuple-return-prefer-dataclass
def get_lists() -> tuple[list[int], list[int]]:
    return [], []


# 3+ elements force positional access even when all types differ
# ruleid: tuple-return-prefer-dataclass
def get_stats() -> tuple[int, str, float]:
    return 0, "", 0.0


# ruleid: tuple-return-prefer-dataclass
def get_more_stats() -> tuple[int, str, float, bool]:
    return 0, "", 0.0, True


# ruleid: tuple-return-prefer-dataclass
async def get_async_range() -> tuple[int, int]:
    return 0, 1


class Widget:
    # ruleid: tuple-return-prefer-dataclass
    def size(self) -> tuple[int, int]:
        return 0, 0


# Small tuples with unambiguous, differently typed elements are fine
# ok: tuple-return-prefer-dataclass
def get_user() -> tuple[str, int]:
    return "", 0


# Homogeneous variable-length tuples have no fixed fields to name
# ok: tuple-return-prefer-dataclass
def get_ids() -> tuple[int, ...]:
    return (1, 2)


# Tuple parameters and locals are out of scope; only return annotations
# ok: tuple-return-prefer-dataclass
def takes_pair(pair: tuple[int, int]) -> None:
    coords: tuple[int, int] = pair


# Unannotated returns are mypy's job, not this rule's
# ok: tuple-return-prefer-dataclass
def unannotated():
    return 0, 1


# ok: tuple-return-prefer-dataclass
def get_name() -> str:
    return ""
