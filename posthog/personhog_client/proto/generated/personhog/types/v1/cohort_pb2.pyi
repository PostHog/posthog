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
