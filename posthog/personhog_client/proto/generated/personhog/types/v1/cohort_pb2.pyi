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

class CohortMembership(_message.Message):
    __slots__ = ("cohort_id", "is_member")
    COHORT_ID_FIELD_NUMBER: _ClassVar[int]
    IS_MEMBER_FIELD_NUMBER: _ClassVar[int]
    cohort_id: int
    is_member: bool

    def __init__(self, cohort_id: _Optional[int] = ..., is_member: bool = ...) -> None: ...

class CheckCohortMembershipRequest(_message.Message):
    __slots__ = ("person_id", "cohort_ids", "read_options")
    PERSON_ID_FIELD_NUMBER: _ClassVar[int]
    COHORT_IDS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    person_id: int
    cohort_ids: _containers.RepeatedScalarFieldContainer[int]
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        person_id: _Optional[int] = ...,
        cohort_ids: _Optional[_Iterable[int]] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class CohortMembershipResponse(_message.Message):
    __slots__ = ("memberships",)
    MEMBERSHIPS_FIELD_NUMBER: _ClassVar[int]
    memberships: _containers.RepeatedCompositeFieldContainer[CohortMembership]

    def __init__(self, memberships: _Optional[_Iterable[_Union[CohortMembership, _Mapping]]] = ...) -> None: ...

class CountCohortMembersRequest(_message.Message):
    __slots__ = ("cohort_ids", "read_options")
    COHORT_IDS_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    cohort_ids: _containers.RepeatedScalarFieldContainer[int]
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        cohort_ids: _Optional[_Iterable[int]] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class CountCohortMembersResponse(_message.Message):
    __slots__ = ("count",)
    COUNT_FIELD_NUMBER: _ClassVar[int]
    count: int

    def __init__(self, count: _Optional[int] = ...) -> None: ...

class DeleteCohortMemberRequest(_message.Message):
    __slots__ = ("cohort_id", "person_id")
    COHORT_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_ID_FIELD_NUMBER: _ClassVar[int]
    cohort_id: int
    person_id: int

    def __init__(self, cohort_id: _Optional[int] = ..., person_id: _Optional[int] = ...) -> None: ...

class DeleteCohortMemberResponse(_message.Message):
    __slots__ = ("deleted",)
    DELETED_FIELD_NUMBER: _ClassVar[int]
    deleted: bool

    def __init__(self, deleted: bool = ...) -> None: ...

class DeleteCohortMembersBulkRequest(_message.Message):
    __slots__ = ("cohort_ids", "batch_size")
    COHORT_IDS_FIELD_NUMBER: _ClassVar[int]
    BATCH_SIZE_FIELD_NUMBER: _ClassVar[int]
    cohort_ids: _containers.RepeatedScalarFieldContainer[int]
    batch_size: int

    def __init__(self, cohort_ids: _Optional[_Iterable[int]] = ..., batch_size: _Optional[int] = ...) -> None: ...

class DeleteCohortMembersBulkResponse(_message.Message):
    __slots__ = ("deleted_count",)
    DELETED_COUNT_FIELD_NUMBER: _ClassVar[int]
    deleted_count: int

    def __init__(self, deleted_count: _Optional[int] = ...) -> None: ...

class InsertCohortMembersRequest(_message.Message):
    __slots__ = ("cohort_id", "person_ids", "version")
    COHORT_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_IDS_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    cohort_id: int
    person_ids: _containers.RepeatedScalarFieldContainer[int]
    version: int

    def __init__(
        self,
        cohort_id: _Optional[int] = ...,
        person_ids: _Optional[_Iterable[int]] = ...,
        version: _Optional[int] = ...,
    ) -> None: ...

class InsertCohortMembersResponse(_message.Message):
    __slots__ = ("inserted_count",)
    INSERTED_COUNT_FIELD_NUMBER: _ClassVar[int]
    inserted_count: int

    def __init__(self, inserted_count: _Optional[int] = ...) -> None: ...

class ListCohortMemberIdsRequest(_message.Message):
    __slots__ = ("cohort_id", "cursor", "limit", "read_options")
    COHORT_ID_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    READ_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    cohort_id: int
    cursor: int
    limit: int
    read_options: _common_pb2.ReadOptions

    def __init__(
        self,
        cohort_id: _Optional[int] = ...,
        cursor: _Optional[int] = ...,
        limit: _Optional[int] = ...,
        read_options: _Optional[_Union[_common_pb2.ReadOptions, _Mapping]] = ...,
    ) -> None: ...

class ListCohortMemberIdsResponse(_message.Message):
    __slots__ = ("person_ids", "next_cursor")
    PERSON_IDS_FIELD_NUMBER: _ClassVar[int]
    NEXT_CURSOR_FIELD_NUMBER: _ClassVar[int]
    person_ids: _containers.RepeatedScalarFieldContainer[int]
    next_cursor: int

    def __init__(self, person_ids: _Optional[_Iterable[int]] = ..., next_cursor: _Optional[int] = ...) -> None: ...
