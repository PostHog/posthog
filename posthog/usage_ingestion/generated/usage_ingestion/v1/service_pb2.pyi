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

class CounterGranularity(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    COUNTER_GRANULARITY_UNSPECIFIED: _ClassVar[CounterGranularity]
    COUNTER_GRANULARITY_HOUR: _ClassVar[CounterGranularity]
    COUNTER_GRANULARITY_DAY: _ClassVar[CounterGranularity]

COUNTER_GRANULARITY_UNSPECIFIED: CounterGranularity
COUNTER_GRANULARITY_HOUR: CounterGranularity
COUNTER_GRANULARITY_DAY: CounterGranularity

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

class GetUsageCountersRequest(_message.Message):
    __slots__ = ("team_id", "organization_id", "start_timestamp_ms", "end_timestamp_ms", "granularity")
    TEAM_ID_FIELD_NUMBER: _ClassVar[int]
    ORGANIZATION_ID_FIELD_NUMBER: _ClassVar[int]
    START_TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    END_TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    GRANULARITY_FIELD_NUMBER: _ClassVar[int]
    team_id: int
    organization_id: str
    start_timestamp_ms: int
    end_timestamp_ms: int
    granularity: CounterGranularity

    def __init__(
        self,
        team_id: _Optional[int] = ...,
        organization_id: _Optional[str] = ...,
        start_timestamp_ms: _Optional[int] = ...,
        end_timestamp_ms: _Optional[int] = ...,
        granularity: _Optional[_Union[CounterGranularity, str]] = ...,
    ) -> None: ...

class UsageCounterValue(_message.Message):
    __slots__ = ("usage_key", "unit", "quantity")
    USAGE_KEY_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    usage_key: str
    unit: str
    quantity: int

    def __init__(
        self, usage_key: _Optional[str] = ..., unit: _Optional[str] = ..., quantity: _Optional[int] = ...
    ) -> None: ...

class UsageCounterBucket(_message.Message):
    __slots__ = ("start_timestamp_ms", "values")
    START_TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    VALUES_FIELD_NUMBER: _ClassVar[int]
    start_timestamp_ms: int
    values: _containers.RepeatedCompositeFieldContainer[UsageCounterValue]

    def __init__(
        self,
        start_timestamp_ms: _Optional[int] = ...,
        values: _Optional[_Iterable[_Union[UsageCounterValue, _Mapping]]] = ...,
    ) -> None: ...

class GetUsageCountersResponse(_message.Message):
    __slots__ = ("buckets",)
    BUCKETS_FIELD_NUMBER: _ClassVar[int]
    buckets: _containers.RepeatedCompositeFieldContainer[UsageCounterBucket]

    def __init__(self, buckets: _Optional[_Iterable[_Union[UsageCounterBucket, _Mapping]]] = ...) -> None: ...
