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

class Group(_message.Message):
    __slots__ = (
        "id",
        "team_id",
        "group_type_index",
        "group_key",
        "group_properties",
        "created_at",
        "properties_last_updated_at",
        "properties_last_operation",
        "version",
    )
    ID_FIELD_NUMBER: _ClassVar[int]
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    GROUP_TYPE_INDEX_FIELD_NUMBER: _ClassVar[int]
    GROUP_KEY_FIELD_NUMBER: _ClassVar[int]
    GROUP_PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_LAST_UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_LAST_OPERATION_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    id: int
    team_id: int
    group_type_index: int
    group_key: str
    group_properties: bytes
    created_at: int
    properties_last_updated_at: bytes
    properties_last_operation: bytes
    version: int

    def __init__(
        self,
        id: _Optional[int] = ...,
        team_id: _Optional[int] = ...,
        group_type_index: _Optional[int] = ...,
        group_key: _Optional[str] = ...,
        group_properties: _Optional[bytes] = ...,
        created_at: _Optional[int] = ...,
        properties_last_updated_at: _Optional[bytes] = ...,
        properties_last_operation: _Optional[bytes] = ...,
        version: _Optional[int] = ...,
    ) -> None: ...

class GroupTypeMapping(_message.Message):
    __slots__ = (
        "id",
        "team_id",
        "project_id",
        "group_type",
        "group_type_index",
        "name_singular",
        "name_plural",
        "default_columns",
        "detail_dashboard_id",
        "created_at",
    )
    ID_FIELD_NUMBER: _ClassVar[int]
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    GROUP_TYPE_FIELD_NUMBER: _ClassVar[int]
    GROUP_TYPE_INDEX_FIELD_NUMBER: _ClassVar[int]
    NAME_SINGULAR_FIELD_NUMBER: _ClassVar[int]
    NAME_PLURAL_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_COLUMNS_FIELD_NUMBER: _ClassVar[int]
    DETAIL_DASHBOARD_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    id: int
    team_id: int
    project_id: int
    group_type: str
    group_type_index: int
    name_singular: str
    name_plural: str
    default_columns: bytes
    detail_dashboard_id: int
    created_at: int

    def __init__(
        self,
        id: _Optional[int] = ...,
        team_id: _Optional[int] = ...,
        project_id: _Optional[int] = ...,
        group_type: _Optional[str] = ...,
        group_type_index: _Optional[int] = ...,
        name_singular: _Optional[str] = ...,
        name_plural: _Optional[str] = ...,
        default_columns: _Optional[bytes] = ...,
        detail_dashboard_id: _Optional[int] = ...,
        created_at: _Optional[int] = ...,
    ) -> None: ...

class GroupWithKey(_message.Message):
    __slots__ = ("key", "group")
    KEY_FIELD_NUMBER: _ClassVar[int]
    GROUP_FIELD_NUMBER: _ClassVar[int]
    key: _common_pb2.GroupKey
    group: Group

    def __init__(
        self,
        key: _Optional[_Union[_common_pb2.GroupKey, _Mapping]] = ...,
        group: _Optional[_Union[Group, _Mapping]] = ...,
    ) -> None: ...

class GroupTypeMappingsByKey(_message.Message):
    __slots__ = ("key", "mappings")
    KEY_FIELD_NUMBER: _ClassVar[int]
    MAPPINGS_FIELD_NUMBER: _ClassVar[int]
    key: int
    mappings: _containers.RepeatedCompositeFieldContainer[GroupTypeMapping]

    def __init__(
        self, key: _Optional[int] = ..., mappings: _Optional[_Iterable[_Union[GroupTypeMapping, _Mapping]]] = ...
    ) -> None: ...

class GetGroupRequest(_message.Message):
    __slots__ = ("team_id", "group_type_index", "group_key", "read_options")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    GROUP_TYPE_INDEX_FIELD_NUMBER: _ClassVar[int]
    GROUP_KEY_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    group_type_index: int
    group_key: str
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        group_type_index: _Optional[int] = ...,
        group_key: _Optional[str] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class GetGroupResponse(_message.Message):
    __slots__ = ("group",)
    GROUP_FIELD_NUMBER: _ClassVar[int]
    group: Group

    def __init__(self, group: _Optional[_Union[Group, _Mapping]] = ...) -> None: ...

class GetGroupsRequest(_message.Message):
    __slots__ = ("team_id", "group_identifiers", "read_options")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    GROUP_IDENTIFIERS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    group_identifiers: _containers.RepeatedCompositeFieldContainer[_common_pb2.GroupIdentifier]
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        group_identifiers: _Optional[_Iterable[_Union[_common_pb2.GroupIdentifier, _Mapping]]] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class GroupsResponse(_message.Message):
    __slots__ = ("groups", "missing_groups")
    GROUPS_FIELD_NUMBER: _ClassVar[int]
    MISSING_GROUPS_FIELD_NUMBER: _ClassVar[int]
    groups: _containers.RepeatedCompositeFieldContainer[Group]
    missing_groups: _containers.RepeatedCompositeFieldContainer[_common_pb2.GroupIdentifier]

    def __init__(
        self,
        groups: _Optional[_Iterable[_Union[Group, _Mapping]]] = ...,
        missing_groups: _Optional[_Iterable[_Union[_common_pb2.GroupIdentifier, _Mapping]]] = ...,
    ) -> None: ...

class GetGroupsBatchRequest(_message.Message):
    __slots__ = ("keys", "read_options")
    KEYS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    keys: _containers.RepeatedCompositeFieldContainer[_common_pb2.GroupKey]
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        keys: _Optional[_Iterable[_Union[_common_pb2.GroupKey, _Mapping]]] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class GetGroupsBatchResponse(_message.Message):
    __slots__ = ("results",)
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[GroupWithKey]

    def __init__(self, results: _Optional[_Iterable[_Union[GroupWithKey, _Mapping]]] = ...) -> None: ...

class GetGroupTypeMappingsByTeamIdRequest(_message.Message):
    __slots__ = ("team_id", "read_options")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    read_options: _common_pb2.ReadOptions

    def __init__(
        self, team_id: _Optional[int] = ..., read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...
    ) -> None: ...

class GetGroupTypeMappingsByTeamIdsRequest(_message.Message):
    __slots__ = ("team_ids", "read_options")
    TEAM_IDS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    team_ids: _containers.RepeatedScalarFieldContainer[int]
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        team_ids: _Optional[_Iterable[int]] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class GetGroupTypeMappingsByProjectIdRequest(_message.Message):
    __slots__ = ("project_id", "read_options")
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    project_id: int
    read_options: _common_pb2.ReadOptions

    def __init__(
        self, project_id: _Optional[int] = ..., read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...
    ) -> None: ...

class GetGroupTypeMappingsByProjectIdsRequest(_message.Message):
    __slots__ = ("project_ids", "read_options")
    PROJECT_IDS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    project_ids: _containers.RepeatedScalarFieldContainer[int]
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        project_ids: _Optional[_Iterable[int]] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class GroupTypeMappingsResponse(_message.Message):
    __slots__ = ("mappings",)
    MAPPINGS_FIELD_NUMBER: _ClassVar[int]
    mappings: _containers.RepeatedCompositeFieldContainer[GroupTypeMapping]

    def __init__(self, mappings: _Optional[_Iterable[_Union[GroupTypeMapping, _Mapping]]] = ...) -> None: ...

class GroupTypeMappingsBatchResponse(_message.Message):
    __slots__ = ("results",)
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[GroupTypeMappingsByKey]

    def __init__(self, results: _Optional[_Iterable[_Union[GroupTypeMappingsByKey, _Mapping]]] = ...) -> None: ...
