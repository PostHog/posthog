# Test cases for prefer-frozen-dataclasses.
# ruff: noqa
import dataclasses
from dataclasses import dataclass

from posthog.dataclasses import frozen


# ruleid: prefer-frozen-dataclasses
@dataclass
class BareDecorator:
    value: int


# ruleid: prefer-frozen-dataclasses
@dataclass()
class EmptyCall:
    value: int


# ruleid: prefer-frozen-dataclasses
@dataclass(slots=True, kw_only=True)
class FlagsButNoFrozenChoice:
    value: int


# ruleid: prefer-frozen-dataclasses
@dataclasses.dataclass
class BareModuleAttribute:
    value: int


# ruleid: prefer-frozen-dataclasses
@dataclasses.dataclass(kw_only=True)
class ModuleAttributeNoFrozenChoice:
    value: int


# ok: prefer-frozen-dataclasses
@frozen
class HouseDefault:
    value: int


# ok: prefer-frozen-dataclasses
@frozen(slots=False)
class HouseDefaultWithOverride:
    value: int


# ok: prefer-frozen-dataclasses
@dataclass(frozen=True, kw_only=True, slots=True)
class ExplicitFrozen:
    value: int


# ok: prefer-frozen-dataclasses
@dataclass(frozen=False)
class ExplicitlyMutable:
    value: int


# ok: prefer-frozen-dataclasses
@dataclasses.dataclass(frozen=True)
class ExplicitFrozenModuleAttribute:
    value: int


# The pydantic import below excludes everything after it, mirroring real files
# where pydantic's dataclass is imported at the top.
from pydantic.dataclasses import dataclass  # noqa: E402


# ok: prefer-frozen-dataclasses
@dataclass
class PydanticDataclass:
    value: int


# The module-attribute form is stdlib even in a pydantic-importing file.
# ruleid: prefer-frozen-dataclasses
@dataclasses.dataclass
class StdlibAfterPydanticImport:
    value: int
