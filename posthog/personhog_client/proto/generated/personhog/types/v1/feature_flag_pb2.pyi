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

class HashKeyOverride(_message.Message):
    __slots__ = ("feature_flag_key", "hash_key")
    FEATURE_FLAG_KEY_FIELD_NUMBER: _ClassVar[int]
    HASH_KEY_FIELD_NUMBER: _ClassVar[int]
    feature_flag_key: str
    hash_key: str

    def __init__(self, feature_flag_key: _Optional[str] = ..., hash_key: _Optional[str] = ...) -> None: ...

class HashKeyOverrideContext(_message.Message):
    __slots__ = ("person_id", "distinct_id", "overrides", "existing_feature_flag_keys")
    PERSON_ID_FIELD_NUMBER: _ClassVar[int]
    DISTINCT_ID_FIELD_NUMBER: _ClassVar[int]
    OVERRIDES_FIELD_NUMBER: _ClassVar[int]
    EXISTING_FEATURE_FLAG_KEYS_FIELD_NUMBER: _ClassVar[int]
    person_id: int
    distinct_id: str
    overrides: _containers.RepeatedCompositeFieldContainer[HashKeyOverride]
    existing_feature_flag_keys: _containers.RepeatedScalarFieldContainer[str]

    def __init__(
        self,
        person_id: _Optional[int] = ...,
        distinct_id: _Optional[str] = ...,
        overrides: _Optional[_Iterable[_Union[HashKeyOverride, _Mapping]]] = ...,
        existing_feature_flag_keys: _Optional[_Iterable[str]] = ...,
    ) -> None: ...

class GetHashKeyOverrideContextRequest(_message.Message):
    __slots__ = ("team_id", "distinct_ids", "check_person_exists", "read_options")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    DISTINCT_IDS_FIELD_NUMBER: _ClassVar[int]
    CHECK_PERSON_EXISTS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    distinct_ids: _containers.RepeatedScalarFieldContainer[str]
    check_person_exists: bool
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        distinct_ids: _Optional[_Iterable[str]] = ...,
        check_person_exists: bool = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class GetHashKeyOverrideContextResponse(_message.Message):
    __slots__ = ("results",)
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[HashKeyOverrideContext]

    def __init__(self, results: _Optional[_Iterable[_Union[HashKeyOverrideContext, _Mapping]]] = ...) -> None: ...

class UpsertHashKeyOverridesRequest(_message.Message):
    __slots__ = ("team_id", "distinct_ids", "hash_key", "feature_flag_keys")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    DISTINCT_IDS_FIELD_NUMBER: _ClassVar[int]
    HASH_KEY_FIELD_NUMBER: _ClassVar[int]
    FEATURE_FLAG_KEYS_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    distinct_ids: _containers.RepeatedScalarFieldContainer[str]
    hash_key: str
    feature_flag_keys: _containers.RepeatedScalarFieldContainer[str]

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        distinct_ids: _Optional[_Iterable[str]] = ...,
        hash_key: _Optional[str] = ...,
        feature_flag_keys: _Optional[_Iterable[str]] = ...,
    ) -> None: ...

class UpsertHashKeyOverridesResponse(_message.Message):
    __slots__ = ("inserted_count",)
    INSERTED_COUNT_FIELD_NUMBER: _ClassVar[int]
    inserted_count: int

    def __init__(self, inserted_count: _Optional[int] = ...) -> None: ...

class DeleteHashKeyOverridesByTeamsRequest(_message.Message):
    __slots__ = ("team_ids",)
    TEAM_IDS_FIELD_NUMBER: _ClassVar[int]
    team_ids: _containers.RepeatedScalarFieldContainer[int]

    def __init__(self, team_ids: _Optional[_Iterable[int]] = ...) -> None: ...

class DeleteHashKeyOverridesByTeamsResponse(_message.Message):
    __slots__ = ("deleted_count",)
    DELETED_COUNT_FIELD_NUMBER: _ClassVar[int]
    deleted_count: int

    def __init__(self, deleted_count: _Optional[int] = ...) -> None: ...
