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
from personhog.types.v1 import common_pb2 as _common_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class Person(_message.Message):
    __slots__ = (
        "id",
        "uuid",
        "team_id",
        "properties",
        "properties_last_updated_at",
        "properties_last_operation",
        "created_at",
        "version",
        "is_identified",
        "is_user_id",
        "last_seen_at",
    )
    ID_FIELD_NUMBER: _ClassVar[int]
    UUID_FIELD_NUMBER: _ClassVar[int]
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_LAST_UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_LAST_OPERATION_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    IS_IDENTIFIED_FIELD_NUMBER: _ClassVar[int]
    IS_USER_ID_FIELD_NUMBER: _ClassVar[int]
    LAST_SEEN_AT_FIELD_NUMBER: _ClassVar[int]
    id: int
    uuid: str
    team_id: int
    properties: bytes
    properties_last_updated_at: bytes
    properties_last_operation: bytes
    created_at: int
    version: int
    is_identified: bool
    is_user_id: bool
    last_seen_at: int

    def __init__(
        self,
        id: _Optional[int] = ...,
        uuid: _Optional[str] = ...,
        team_id: _Optional[int] = ...,
        properties: _Optional[bytes] = ...,
        properties_last_updated_at: _Optional[bytes] = ...,
        properties_last_operation: _Optional[bytes] = ...,
        created_at: _Optional[int] = ...,
        version: _Optional[int] = ...,
        is_identified: bool = ...,
        is_user_id: bool = ...,
        last_seen_at: _Optional[int] = ...,
    ) -> None: ...

class DistinctIdWithVersion(_message.Message):
    __slots__ = ("distinct_id", "version")
    DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    distinct_id: str
    version: int

    def __init__(self, distinct_id: _Optional[str] = ..., version: _Optional[int] = ...) -> None: ...

class PersonWithDistinctIds(_message.Message):
    __slots__ = ("distinct_id", "person")
    DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_FIELD_NUMBER: _ClassVar[int]
    distinct_id: str
    person: Person

    def __init__(
        self, distinct_id: _Optional[str] = ..., person: _Optional[_Union[Person, _Mapping]] = ...
    ) -> None: ...

class PersonDistinctIds(_message.Message):
    __slots__ = ("person_id", "distinct_ids")
    PERSON_ID_FIELD_NUMBER: _ClassVar[int]
    DISTINCT_IDS_FIELD_NUMBER: _ClassVar[int]
    person_id: int
    distinct_ids: _containers.RepeatedCompositeFieldContainer[DistinctIdWithVersion]

    def __init__(
        self,
        person_id: _Optional[int] = ...,
        distinct_ids: _Optional[_Iterable[_Union[DistinctIdWithVersion, _Mapping]]] = ...,
    ) -> None: ...

class PersonWithTeamDistinctId(_message.Message):
    __slots__ = ("key", "person")
    KEY_FIELD_NUMBER: _ClassVar[int]
    PERSON_FIELD_NUMBER: _ClassVar[int]
    key: _common_pb2.TeamDistinctId
    person: Person

    def __init__(
        self,
        key: _Optional[_Union[_common_pb2.TeamDistinctId, _Mapping]] = ...,
        person: _Optional[_Union[Person, _Mapping]] = ...,
    ) -> None: ...

class GetPersonRequest(_message.Message):
    __slots__ = ("team_id", "person_id", "read_options")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_ID_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    person_id: int
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        person_id: _Optional[int] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class GetPersonResponse(_message.Message):
    __slots__ = ("person",)
    PERSON_FIELD_NUMBER: _ClassVar[int]
    person: Person

    def __init__(self, person: _Optional[_Union[Person, _Mapping]] = ...) -> None: ...

class GetPersonsRequest(_message.Message):
    __slots__ = ("team_id", "person_ids", "read_options")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_IDS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    person_ids: _containers.RepeatedScalarFieldContainer[int]
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        person_ids: _Optional[_Iterable[int]] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class PersonsResponse(_message.Message):
    __slots__ = ("persons", "missing_ids")
    PERSONS_FIELD_NUMBER: _ClassVar[int]
    MISSING_IDS_FIELD_NUMBER: _ClassVar[int]
    persons: _containers.RepeatedCompositeFieldContainer[Person]
    missing_ids: _containers.RepeatedScalarFieldContainer[int]

    def __init__(
        self,
        persons: _Optional[_Iterable[_Union[Person, _Mapping]]] = ...,
        missing_ids: _Optional[_Iterable[int]] = ...,
    ) -> None: ...

class GetPersonByUuidRequest(_message.Message):
    __slots__ = ("team_id", "uuid", "read_options")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    UUID_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    uuid: str
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        uuid: _Optional[str] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class GetPersonsByUuidsRequest(_message.Message):
    __slots__ = ("team_id", "uuids", "read_options")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    UUIDS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    uuids: _containers.RepeatedScalarFieldContainer[str]
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        uuids: _Optional[_Iterable[str]] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class GetPersonByDistinctIdRequest(_message.Message):
    __slots__ = ("team_id", "distinct_id", "read_options")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    distinct_id: str
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        distinct_id: _Optional[str] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class GetPersonsByDistinctIdsInTeamRequest(_message.Message):
    __slots__ = ("team_id", "distinct_ids", "read_options")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    DISTINCT_IDS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    distinct_ids: _containers.RepeatedScalarFieldContainer[str]
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        distinct_ids: _Optional[_Iterable[str]] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class PersonsByDistinctIdsInTeamResponse(_message.Message):
    __slots__ = ("results",)
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[PersonWithDistinctIds]

    def __init__(self, results: _Optional[_Iterable[_Union[PersonWithDistinctIds, _Mapping]]] = ...) -> None: ...

class GetPersonsByDistinctIdsRequest(_message.Message):
    __slots__ = ("team_distinct_ids", "read_options")
    TEAM_DISTINCT_IDS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_distinct_ids: _containers.RepeatedCompositeFieldContainer[_common_pb2.TeamDistinctId]
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        team_distinct_ids: _Optional[_Iterable[_Union[_common_pb2.TeamDistinctId, _Mapping]]] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class PersonsByDistinctIdsResponse(_message.Message):
    __slots__ = ("results",)
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[PersonWithTeamDistinctId]

    def __init__(self, results: _Optional[_Iterable[_Union[PersonWithTeamDistinctId, _Mapping]]] = ...) -> None: ...

class GetDistinctIdsForPersonRequest(_message.Message):
    __slots__ = ("team_id", "person_id", "read_options", "limit")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_ID_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    person_id: int
    read_options: _common_pb2.ReadOptions
    limit: int

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        person_id: _Optional[int] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
        limit: _Optional[int] = ...,
    ) -> None: ...

class GetDistinctIdsForPersonResponse(_message.Message):
    __slots__ = ("distinct_ids",)
    DISTINCT_IDS_FIELD_NUMBER: _ClassVar[int]
    distinct_ids: _containers.RepeatedCompositeFieldContainer[DistinctIdWithVersion]

    def __init__(self, distinct_ids: _Optional[_Iterable[_Union[DistinctIdWithVersion, _Mapping]]] = ...) -> None: ...

class GetDistinctIdsForPersonsRequest(_message.Message):
    __slots__ = ("team_id", "person_ids", "read_options", "limit_per_person")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_IDS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_PER_PERSON_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    person_ids: _containers.RepeatedScalarFieldContainer[int]
    read_options: _common_pb2.ReadOptions
    limit_per_person: int

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        person_ids: _Optional[_Iterable[int]] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
        limit_per_person: _Optional[int] = ...,
    ) -> None: ...

class GetDistinctIdsForPersonsResponse(_message.Message):
    __slots__ = ("person_distinct_ids",)
    PERSON_DISTINCT_IDS_FIELD_NUMBER: _ClassVar[int]
    person_distinct_ids: _containers.RepeatedCompositeFieldContainer[PersonDistinctIds]

    def __init__(
        self, person_distinct_ids: _Optional[_Iterable[_Union[PersonDistinctIds, _Mapping]]] = ...
    ) -> None: ...
