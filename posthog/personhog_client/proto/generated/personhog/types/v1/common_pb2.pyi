from typing import (
    ClassVar as _ClassVar,
    Optional as _Optional,
    Union as _Union,
)

from google.protobuf import (
    descriptor as _descriptor,
    message as _message,
)
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

DESCRIPTOR: _descriptor.FileDescriptor

class ConsistencyLevel(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CONSISTENCY_LEVEL_UNSPECIFIED: _ClassVar[ConsistencyLevel]
    CONSISTENCY_LEVEL_EVENTUAL: _ClassVar[ConsistencyLevel]
    CONSISTENCY_LEVEL_STRONG: _ClassVar[ConsistencyLevel]

CONSISTENCY_LEVEL_UNSPECIFIED: ConsistencyLevel
CONSISTENCY_LEVEL_EVENTUAL: ConsistencyLevel
CONSISTENCY_LEVEL_STRONG: ConsistencyLevel

class ReadOptions(_message.Message):
    __slots__ = ("consistency",)
    CONSISTENCY_FIELD_NUMBER: _ClassVar[int]
    consistency: ConsistencyLevel

    def __init__(self, consistency: _Optional[_Union[ConsistencyLevel, str]] = ...) -> None: ...

class TeamDistinctId(_message.Message):
    __slots__ = ("team_id", "distinct_id")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    distinct_id: str

    def __init__(self, team_id: _Optional[int] = ..., distinct_id: _Optional[str] = ...) -> None: ...

class GroupKey(_message.Message):
    __slots__ = ("team_id", "group_type_index", "group_key")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    GROUP_TYPE_INDEX_FIELD_NUMBER: _ClassVar[int]
    GROUP_KEY_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    group_type_index: int
    group_key: str

    def __init__(
        self, team_id: _Optional[int] = ..., group_type_index: _Optional[int] = ..., group_key: _Optional[str] = ...
    ) -> None: ...

class GroupIdentifier(_message.Message):
    __slots__ = ("group_type_index", "group_key")
    GROUP_TYPE_INDEX_FIELD_NUMBER: _ClassVar[int]
    GROUP_KEY_FIELD_NUMBER: _ClassVar[int]
    group_type_index: int
    group_key: str

    def __init__(self, group_type_index: _Optional[int] = ..., group_key: _Optional[str] = ...) -> None: ...
