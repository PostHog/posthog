from collections.abc import (
    Iterable as _Iterable,
    Mapping as _Mapping,
)
from typing import (
    ClassVar as _ClassVar,
    Optional as _Optional,
    Union as _Union,
)

from google.protobuf import (
    descriptor as _descriptor,
    message as _message,
)
from google.protobuf.internal import containers as _containers
from personhog.types.v1 import person_pb2 as _person_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class UpdatePersonPropertiesRequest(_message.Message):
    __slots__ = (
        "team_id",
        "person_id",
        "event_name",
        "set_properties",
        "set_once_properties",
        "unset_properties",
        "partition",
    )
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_ID_FIELD_NUMBER: _ClassVar[int]
    EVENT_NAME_FIELD_NUMBER: _ClassVar[int]
    SET_PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    SET_ONCE_PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    UNSET_PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    PARTITION_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    person_id: int
    event_name: str
    set_properties: bytes
    set_once_properties: bytes
    unset_properties: _containers.RepeatedScalarFieldContainer[str]
    partition: int

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        person_id: _Optional[int] = ...,
        event_name: _Optional[str] = ...,
        set_properties: _Optional[bytes] = ...,
        set_once_properties: _Optional[bytes] = ...,
        unset_properties: _Optional[_Iterable[str]] = ...,
        partition: _Optional[int] = ...,
    ) -> None: ...

class LeaderGetPersonRequest(_message.Message):
    __slots__ = ("team_id", "person_id", "partition")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_ID_FIELD_NUMBER: _ClassVar[int]
    PARTITION_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    person_id: int
    partition: int

    def __init__(
        self, team_id: _Optional[int] = ..., person_id: _Optional[int] = ..., partition: _Optional[int] = ...
    ) -> None: ...

class UpdatePersonPropertiesResponse(_message.Message):
    __slots__ = ("person", "updated")
    PERSON_FIELD_NUMBER: _ClassVar[int]
    UPDATED_FIELD_NUMBER: _ClassVar[int]
    person: _person_pb2.Person
    updated: bool

    def __init__(self, person: _Optional[_Union[_person_pb2.Person, _Mapping]] = ..., updated: bool = ...) -> None: ...
