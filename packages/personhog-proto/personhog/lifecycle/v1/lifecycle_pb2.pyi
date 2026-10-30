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

DESCRIPTOR: _descriptor.FileDescriptor

class DeletePersonOutcome(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DELETE_PERSON_OUTCOME_UNSPECIFIED: _ClassVar[DeletePersonOutcome]
    DELETE_PERSON_OUTCOME_DELETED: _ClassVar[DeletePersonOutcome]
    DELETE_PERSON_OUTCOME_SKIPPED_CONFLICT: _ClassVar[DeletePersonOutcome]
    DELETE_PERSON_OUTCOME_NOT_FOUND: _ClassVar[DeletePersonOutcome]

DELETE_PERSON_OUTCOME_UNSPECIFIED: DeletePersonOutcome
DELETE_PERSON_OUTCOME_DELETED: DeletePersonOutcome
DELETE_PERSON_OUTCOME_SKIPPED_CONFLICT: DeletePersonOutcome
DELETE_PERSON_OUTCOME_NOT_FOUND: DeletePersonOutcome

class DeletePersonsRequest(_message.Message):
    __slots__ = ("team_id", "person_ids", "op_id")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    PERSON_IDS_FIELD_NUMBER: _ClassVar[int]
    OP_ID_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    person_ids: _containers.RepeatedScalarFieldContainer[int]
    op_id: str
    def __init__(
        self, team_id: _Optional[int] = ..., person_ids: _Optional[_Iterable[int]] = ..., op_id: _Optional[str] = ...
    ) -> None: ...

class DeletePersonResult(_message.Message):
    __slots__ = ("person_id", "outcome", "person_version")
    PERSON_ID_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    PERSON_VERSION_FIELD_NUMBER: _ClassVar[int]
    person_id: int
    outcome: DeletePersonOutcome
    person_version: int
    def __init__(
        self,
        person_id: _Optional[int] = ...,
        outcome: _Optional[_Union[DeletePersonOutcome, str]] = ...,
        person_version: _Optional[int] = ...,
    ) -> None: ...

class DeletePersonsResponse(_message.Message):
    __slots__ = ("op_id", "results")
    OP_ID_FIELD_NUMBER: _ClassVar[int]
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    op_id: str
    results: _containers.RepeatedCompositeFieldContainer[DeletePersonResult]
    def __init__(
        self, op_id: _Optional[str] = ..., results: _Optional[_Iterable[_Union[DeletePersonResult, _Mapping]]] = ...
    ) -> None: ...
