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

class BillingUsageRecord(_message.Message):
    __slots__ = ("team_id", "timestamp_ms", "producer_id", "usage_key", "record_id", "quantity", "unit")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    PRODUCER_ID_FIELD_NUMBER: _ClassVar[int]
    USAGE_KEY_FIELD_NUMBER: _ClassVar[int]
    RECORD_ID_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    timestamp_ms: int
    producer_id: str
    usage_key: str
    record_id: str
    quantity: int
    unit: str
    def __init__(
        self,
        team_id: _Optional[int] = ...,
        timestamp_ms: _Optional[int] = ...,
        producer_id: _Optional[str] = ...,
        usage_key: _Optional[str] = ...,
        record_id: _Optional[str] = ...,
        quantity: _Optional[int] = ...,
        unit: _Optional[str] = ...,
    ) -> None: ...

class IngestBillingUsageRequest(_message.Message):
    __slots__ = ("records",)
    RECORDS_FIELD_NUMBER: _ClassVar[int]
    records: _containers.RepeatedCompositeFieldContainer[BillingUsageRecord]
    def __init__(self, records: _Optional[_Iterable[_Union[BillingUsageRecord, _Mapping]]] = ...) -> None: ...

class IngestBillingUsageResponse(_message.Message):
    __slots__ = ("accepted_record_ids",)
    ACCEPTED_RECORD_IDS_FIELD_NUMBER: _ClassVar[int]
    accepted_record_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, accepted_record_ids: _Optional[_Iterable[str]] = ...) -> None: ...
