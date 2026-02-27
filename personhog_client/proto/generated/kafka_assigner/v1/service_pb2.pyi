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

DESCRIPTOR: _descriptor.FileDescriptor

class RegisterRequest(_message.Message):
    __slots__ = ("consumer_name",)
    CONSUMER_NAME_FIELD_NUMBER: _ClassVar[int]
    consumer_name: str
    def __init__(self, consumer_name: _Optional[str] = ...) -> None: ...

class AssignmentCommand(_message.Message):
    __slots__ = ("assignment", "warm", "release")
    ASSIGNMENT_FIELD_NUMBER: _ClassVar[int]
    WARM_FIELD_NUMBER: _ClassVar[int]
    RELEASE_FIELD_NUMBER: _ClassVar[int]
    assignment: AssignmentUpdate
    warm: WarmPartition
    release: ReleasePartition
    def __init__(
        self,
        assignment: _Optional[_Union[AssignmentUpdate, _Mapping]] = ...,
        warm: _Optional[_Union[WarmPartition, _Mapping]] = ...,
        release: _Optional[_Union[ReleasePartition, _Mapping]] = ...,
    ) -> None: ...

class AssignmentUpdate(_message.Message):
    __slots__ = ("assigned", "unassigned")
    ASSIGNED_FIELD_NUMBER: _ClassVar[int]
    UNASSIGNED_FIELD_NUMBER: _ClassVar[int]
    assigned: _containers.RepeatedCompositeFieldContainer[TopicPartition]
    unassigned: _containers.RepeatedCompositeFieldContainer[TopicPartition]
    def __init__(
        self,
        assigned: _Optional[_Iterable[_Union[TopicPartition, _Mapping]]] = ...,
        unassigned: _Optional[_Iterable[_Union[TopicPartition, _Mapping]]] = ...,
    ) -> None: ...

class WarmPartition(_message.Message):
    __slots__ = ("partition", "current_owner")
    PARTITION_FIELD_NUMBER: _ClassVar[int]
    CURRENT_OWNER_FIELD_NUMBER: _ClassVar[int]
    partition: TopicPartition
    current_owner: str
    def __init__(
        self, partition: _Optional[_Union[TopicPartition, _Mapping]] = ..., current_owner: _Optional[str] = ...
    ) -> None: ...

class ReleasePartition(_message.Message):
    __slots__ = ("partition", "new_owner")
    PARTITION_FIELD_NUMBER: _ClassVar[int]
    NEW_OWNER_FIELD_NUMBER: _ClassVar[int]
    partition: TopicPartition
    new_owner: str
    def __init__(
        self, partition: _Optional[_Union[TopicPartition, _Mapping]] = ..., new_owner: _Optional[str] = ...
    ) -> None: ...

class TopicPartition(_message.Message):
    __slots__ = ("topic", "partition")
    TOPIC_FIELD_NUMBER: _ClassVar[int]
    PARTITION_FIELD_NUMBER: _ClassVar[int]
    topic: str
    partition: int
    def __init__(self, topic: _Optional[str] = ..., partition: _Optional[int] = ...) -> None: ...

class PartitionReadyRequest(_message.Message):
    __slots__ = ("consumer_name", "partition")
    CONSUMER_NAME_FIELD_NUMBER: _ClassVar[int]
    PARTITION_FIELD_NUMBER: _ClassVar[int]
    consumer_name: str
    partition: TopicPartition
    def __init__(
        self, consumer_name: _Optional[str] = ..., partition: _Optional[_Union[TopicPartition, _Mapping]] = ...
    ) -> None: ...

class PartitionReadyResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class PartitionReleasedRequest(_message.Message):
    __slots__ = ("consumer_name", "partition")
    CONSUMER_NAME_FIELD_NUMBER: _ClassVar[int]
    PARTITION_FIELD_NUMBER: _ClassVar[int]
    consumer_name: str
    partition: TopicPartition
    def __init__(
        self, consumer_name: _Optional[str] = ..., partition: _Optional[_Union[TopicPartition, _Mapping]] = ...
    ) -> None: ...

class PartitionReleasedResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
