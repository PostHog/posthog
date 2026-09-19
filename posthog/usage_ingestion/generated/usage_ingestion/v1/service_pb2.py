"""Generated protocol buffer code."""

from google.protobuf import (
    descriptor as _descriptor,
    descriptor_pool as _descriptor_pool,
    runtime_version as _runtime_version,
    symbol_database as _symbol_database,
)
from google.protobuf.internal import builder as _builder

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 0, "", "usage_ingestion/v1/service.proto"
)
_sym_db = _symbol_database.Default()
DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n usage_ingestion/v1/service.proto\x12\x12usage_ingestion.v1"\x96\x01\n\x12BillingUsageRecord\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x14\n\x0ctimestamp_ms\x18\x02 \x01(\x03\x12\x13\n\x0bproducer_id\x18\x03 \x01(\t\x12\x11\n\tusage_key\x18\x04 \x01(\t\x12\x11\n\trecord_id\x18\x05 \x01(\t\x12\x10\n\x08quantity\x18\x06 \x01(\x03\x12\x0c\n\x04unit\x18\x07 \x01(\t"T\n\x19IngestBillingUsageRequest\x127\n\x07records\x18\x01 \x03(\x0b2&.usage_ingestion.v1.BillingUsageRecord"9\n\x1aIngestBillingUsageResponse\x12\x1b\n\x13accepted_record_ids\x18\x01 \x03(\t"\xc3\x01\n\x17GetUsageCountersRequest\x12\x11\n\x07team_id\x18\x01 \x01(\x03H\x00\x12\x19\n\x0forganization_id\x18\x02 \x01(\tH\x00\x12\x1a\n\x12start_timestamp_ms\x18\x03 \x01(\x03\x12\x18\n\x10end_timestamp_ms\x18\x04 \x01(\x03\x12;\n\x0bgranularity\x18\x05 \x01(\x0e2&.usage_ingestion.v1.CounterGranularityB\x07\n\x05scope"F\n\x11UsageCounterValue\x12\x11\n\tusage_key\x18\x01 \x01(\t\x12\x0c\n\x04unit\x18\x02 \x01(\t\x12\x10\n\x08quantity\x18\x03 \x01(\x03"g\n\x12UsageCounterBucket\x12\x1a\n\x12start_timestamp_ms\x18\x01 \x01(\x03\x125\n\x06values\x18\x02 \x03(\x0b2%.usage_ingestion.v1.UsageCounterValue"S\n\x18GetUsageCountersResponse\x127\n\x07buckets\x18\x01 \x03(\x0b2&.usage_ingestion.v1.UsageCounterBucket*t\n\x12CounterGranularity\x12#\n\x1fCOUNTER_GRANULARITY_UNSPECIFIED\x10\x00\x12\x1c\n\x18COUNTER_GRANULARITY_HOUR\x10\x01\x12\x1b\n\x17COUNTER_GRANULARITY_DAY\x10\x022\xf4\x01\n\x0eUsageIngestion\x12s\n\x12IngestBillingUsage\x12-.usage_ingestion.v1.IngestBillingUsageRequest\x1a..usage_ingestion.v1.IngestBillingUsageResponse\x12m\n\x10GetUsageCounters\x12+.usage_ingestion.v1.GetUsageCountersRequest\x1a,.usage_ingestion.v1.GetUsageCountersResponseb\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "usage_ingestion.v1.service_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_COUNTERGRANULARITY"]._serialized_start = 814
    _globals["_COUNTERGRANULARITY"]._serialized_end = 930
    _globals["_BILLINGUSAGERECORD"]._serialized_start = 57
    _globals["_BILLINGUSAGERECORD"]._serialized_end = 207
    _globals["_INGESTBILLINGUSAGEREQUEST"]._serialized_start = 209
    _globals["_INGESTBILLINGUSAGEREQUEST"]._serialized_end = 293
    _globals["_INGESTBILLINGUSAGERESPONSE"]._serialized_start = 295
    _globals["_INGESTBILLINGUSAGERESPONSE"]._serialized_end = 352
    _globals["_GETUSAGECOUNTERSREQUEST"]._serialized_start = 355
    _globals["_GETUSAGECOUNTERSREQUEST"]._serialized_end = 550
    _globals["_USAGECOUNTERVALUE"]._serialized_start = 552
    _globals["_USAGECOUNTERVALUE"]._serialized_end = 622
    _globals["_USAGECOUNTERBUCKET"]._serialized_start = 624
    _globals["_USAGECOUNTERBUCKET"]._serialized_end = 727
    _globals["_GETUSAGECOUNTERSRESPONSE"]._serialized_start = 729
    _globals["_GETUSAGECOUNTERSRESPONSE"]._serialized_end = 812
    _globals["_USAGEINGESTION"]._serialized_start = 933
    _globals["_USAGEINGESTION"]._serialized_end = 1177
