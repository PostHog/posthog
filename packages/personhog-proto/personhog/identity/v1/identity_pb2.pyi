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
from google.protobuf.internal import (
    containers as _containers,
    enum_type_wrapper as _enum_type_wrapper,
)

from personhog.types.v1 import person_pb2 as _person_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class MergeSourceOutcome(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MERGE_SOURCE_OUTCOME_UNSPECIFIED: _ClassVar[MergeSourceOutcome]
    MERGE_SOURCE_OUTCOME_MERGED: _ClassVar[MergeSourceOutcome]
    MERGE_SOURCE_OUTCOME_NOOP_SAME_PERSON: _ClassVar[MergeSourceOutcome]
    MERGE_SOURCE_OUTCOME_ATTACHED: _ClassVar[MergeSourceOutcome]
    MERGE_SOURCE_OUTCOME_SKIPPED_ILLEGAL: _ClassVar[MergeSourceOutcome]
    MERGE_SOURCE_OUTCOME_SKIPPED_ALREADY_IDENTIFIED: _ClassVar[MergeSourceOutcome]
    MERGE_SOURCE_OUTCOME_SKIPPED_CONFLICT: _ClassVar[MergeSourceOutcome]
    MERGE_SOURCE_OUTCOME_SKIPPED_MOVE_LIMIT: _ClassVar[MergeSourceOutcome]
    MERGE_SOURCE_OUTCOME_ERROR: _ClassVar[MergeSourceOutcome]
    MERGE_SOURCE_OUTCOME_SKIPPED_REFUSED: _ClassVar[MergeSourceOutcome]

MERGE_SOURCE_OUTCOME_UNSPECIFIED: MergeSourceOutcome
MERGE_SOURCE_OUTCOME_MERGED: MergeSourceOutcome
MERGE_SOURCE_OUTCOME_NOOP_SAME_PERSON: MergeSourceOutcome
MERGE_SOURCE_OUTCOME_ATTACHED: MergeSourceOutcome
MERGE_SOURCE_OUTCOME_SKIPPED_ILLEGAL: MergeSourceOutcome
MERGE_SOURCE_OUTCOME_SKIPPED_ALREADY_IDENTIFIED: MergeSourceOutcome
MERGE_SOURCE_OUTCOME_SKIPPED_CONFLICT: MergeSourceOutcome
MERGE_SOURCE_OUTCOME_SKIPPED_MOVE_LIMIT: MergeSourceOutcome
MERGE_SOURCE_OUTCOME_ERROR: MergeSourceOutcome
MERGE_SOURCE_OUTCOME_SKIPPED_REFUSED: MergeSourceOutcome

class GetOrCreatePersonEntry(_message.Message):
    __slots__ = (
        "team_id",
        "distinct_id",
        "extra_distinct_ids",
        "event_name",
        "set_properties",
        "set_once_properties",
        "created_at",
        "is_identified",
    )
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    EXTRA_DISTINCT_IDS_FIELD_NUMBER: _ClassVar[int]
    EVENT_NAME_FIELD_NUMBER: _ClassVar[int]
    SET_PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    SET_ONCE_PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    IS_IDENTIFIED_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    distinct_id: str
    extra_distinct_ids: _containers.RepeatedScalarFieldContainer[str]
    event_name: str
    set_properties: bytes
    set_once_properties: bytes
    created_at: int
    is_identified: bool
    def __init__(
        self,
        team_id: _Optional[int] = ...,
        distinct_id: _Optional[str] = ...,
        extra_distinct_ids: _Optional[_Iterable[str]] = ...,
        event_name: _Optional[str] = ...,
        set_properties: _Optional[bytes] = ...,
        set_once_properties: _Optional[bytes] = ...,
        created_at: _Optional[int] = ...,
        is_identified: bool = ...,
    ) -> None: ...

class GetOrCreatePersonByDistinctIdRequest(_message.Message):
    __slots__ = ("entry",)
    ENTRY_FIELD_NUMBER: _ClassVar[int]
    entry: GetOrCreatePersonEntry
    def __init__(self, entry: _Optional[_Union[GetOrCreatePersonEntry, _Mapping]] = ...) -> None: ...

class GetOrCreatePersonByDistinctIdResponse(_message.Message):
    __slots__ = ("person", "created")
    PERSON_FIELD_NUMBER: _ClassVar[int]
    CREATED_FIELD_NUMBER: _ClassVar[int]
    person: _person_pb2.Person
    created: bool
    def __init__(self, person: _Optional[_Union[_person_pb2.Person, _Mapping]] = ..., created: bool = ...) -> None: ...

class GetOrCreatePersonsByDistinctIdsRequest(_message.Message):
    __slots__ = ("entries",)
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[GetOrCreatePersonEntry]
    def __init__(self, entries: _Optional[_Iterable[_Union[GetOrCreatePersonEntry, _Mapping]]] = ...) -> None: ...

class GetOrCreatePersonResult(_message.Message):
    __slots__ = ("team_id", "distinct_id", "person", "created", "error")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_FIELD_NUMBER: _ClassVar[int]
    CREATED_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    distinct_id: str
    person: _person_pb2.Person
    created: bool
    error: str
    def __init__(
        self,
        team_id: _Optional[int] = ...,
        distinct_id: _Optional[str] = ...,
        person: _Optional[_Union[_person_pb2.Person, _Mapping]] = ...,
        created: bool = ...,
        error: _Optional[str] = ...,
    ) -> None: ...

class GetOrCreatePersonsByDistinctIdsResponse(_message.Message):
    __slots__ = ("results",)
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[GetOrCreatePersonResult]
    def __init__(self, results: _Optional[_Iterable[_Union[GetOrCreatePersonResult, _Mapping]]] = ...) -> None: ...

class PersonKey(_message.Message):
    __slots__ = ("team_id", "distinct_id")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    distinct_id: str
    def __init__(self, team_id: _Optional[int] = ..., distinct_id: _Optional[str] = ...) -> None: ...

class GetPersonsByDistinctIdsRequest(_message.Message):
    __slots__ = ("keys", "ids_only")
    KEYS_FIELD_NUMBER: _ClassVar[int]
    IDS_ONLY_FIELD_NUMBER: _ClassVar[int]
    keys: _containers.RepeatedCompositeFieldContainer[PersonKey]
    ids_only: bool
    def __init__(self, keys: _Optional[_Iterable[_Union[PersonKey, _Mapping]]] = ..., ids_only: bool = ...) -> None: ...

class GetPersonByDistinctIdResult(_message.Message):
    __slots__ = ("team_id", "distinct_id", "person")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    distinct_id: str
    person: _person_pb2.Person
    def __init__(
        self,
        team_id: _Optional[int] = ...,
        distinct_id: _Optional[str] = ...,
        person: _Optional[_Union[_person_pb2.Person, _Mapping]] = ...,
    ) -> None: ...

class GetPersonsByDistinctIdsResponse(_message.Message):
    __slots__ = ("results",)
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[GetPersonByDistinctIdResult]
    def __init__(self, results: _Optional[_Iterable[_Union[GetPersonByDistinctIdResult, _Mapping]]] = ...) -> None: ...

class GetDistinctIdsForPersonsRequest(_message.Message):
    __slots__ = ("team_id", "person_ids", "limit_per_person")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_IDS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_PER_PERSON_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    person_ids: _containers.RepeatedScalarFieldContainer[int]
    limit_per_person: int
    def __init__(
        self,
        team_id: _Optional[int] = ...,
        person_ids: _Optional[_Iterable[int]] = ...,
        limit_per_person: _Optional[int] = ...,
    ) -> None: ...

class GetDistinctIdsForPersonsResponse(_message.Message):
    __slots__ = ("person_distinct_ids",)
    PERSON_DISTINCT_IDS_FIELD_NUMBER: _ClassVar[int]
    person_distinct_ids: _containers.RepeatedCompositeFieldContainer[_person_pb2.PersonDistinctIds]
    def __init__(
        self, person_distinct_ids: _Optional[_Iterable[_Union[_person_pb2.PersonDistinctIds, _Mapping]]] = ...
    ) -> None: ...

class MergeSource(_message.Message):
    __slots__ = ("source_distinct_id", "event_uuid")
    SOURCE_DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    EVENT_UUID_FIELD_NUMBER: _ClassVar[int]
    source_distinct_id: str
    event_uuid: str
    def __init__(self, source_distinct_id: _Optional[str] = ..., event_uuid: _Optional[str] = ...) -> None: ...

class MergePersonsRequest(_message.Message):
    __slots__ = (
        "team_id",
        "target_distinct_id",
        "sources",
        "event_set",
        "event_set_once",
        "op_id",
        "allow_identified_sources",
        "move_limit",
        "created_at",
        "creator_event_uuid",
    )
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCES_FIELD_NUMBER: _ClassVar[int]
    EVENT_SET_FIELD_NUMBER: _ClassVar[int]
    EVENT_SET_ONCE_FIELD_NUMBER: _ClassVar[int]
    OP_ID_FIELD_NUMBER: _ClassVar[int]
    ALLOW_IDENTIFIED_SOURCES_FIELD_NUMBER: _ClassVar[int]
    MOVE_LIMIT_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    CREATOR_EVENT_UUID_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    target_distinct_id: str
    sources: _containers.RepeatedCompositeFieldContainer[MergeSource]
    event_set: bytes
    event_set_once: bytes
    op_id: str
    allow_identified_sources: bool
    move_limit: int
    created_at: int
    creator_event_uuid: str
    def __init__(
        self,
        team_id: _Optional[int] = ...,
        target_distinct_id: _Optional[str] = ...,
        sources: _Optional[_Iterable[_Union[MergeSource, _Mapping]]] = ...,
        event_set: _Optional[bytes] = ...,
        event_set_once: _Optional[bytes] = ...,
        op_id: _Optional[str] = ...,
        allow_identified_sources: bool = ...,
        move_limit: _Optional[int] = ...,
        created_at: _Optional[int] = ...,
        creator_event_uuid: _Optional[str] = ...,
    ) -> None: ...

class MergeSourceResult(_message.Message):
    __slots__ = ("source_distinct_id", "outcome", "source_person_id", "settled")
    SOURCE_DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    SOURCE_PERSON_ID_FIELD_NUMBER: _ClassVar[int]
    SETTLED_FIELD_NUMBER: _ClassVar[int]
    source_distinct_id: str
    outcome: MergeSourceOutcome
    source_person_id: int
    settled: bool
    def __init__(
        self,
        source_distinct_id: _Optional[str] = ...,
        outcome: _Optional[_Union[MergeSourceOutcome, str]] = ...,
        source_person_id: _Optional[int] = ...,
        settled: bool = ...,
    ) -> None: ...

class MergePersonsResponse(_message.Message):
    __slots__ = ("op_id", "survivor", "results")
    OP_ID_FIELD_NUMBER: _ClassVar[int]
    SURVIVOR_FIELD_NUMBER: _ClassVar[int]
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    op_id: str
    survivor: _person_pb2.Person
    results: _containers.RepeatedCompositeFieldContainer[MergeSourceResult]
    def __init__(
        self,
        op_id: _Optional[str] = ...,
        survivor: _Optional[_Union[_person_pb2.Person, _Mapping]] = ...,
        results: _Optional[_Iterable[_Union[MergeSourceResult, _Mapping]]] = ...,
    ) -> None: ...
