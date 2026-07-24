import { Counter, Histogram } from 'prom-client'

export const aiCostLookupCounter = new Counter({
    name: 'llma_ai_cost_lookup_total',
    help: 'AI model cost lookup outcomes',
    labelNames: ['status'],
})

export const aiErrorNormalizationCounter = new Counter({
    name: 'llma_ai_error_normalization_total',
    help: 'AI error normalization outcomes',
    labelNames: ['status'],
})

export const aiCostModalityExtractionCounter = new Counter({
    name: 'llma_ai_cost_modality_extraction_total',
    help: 'AI cost modality token extraction outcomes by source',
    labelNames: ['status', 'source'],
})

export const aiCostTotalOutcomeCounter = new Counter({
    name: 'llma_ai_cost_outcome_total',
    help: 'Outcome of total cost calculation (positive, zero, negative)',
    labelNames: ['outcome'],
})

export const aiToolCallExtractionCounter = new Counter({
    name: 'llma_ai_tool_call_extraction_total',
    help: 'AI tool call extraction outcomes',
    labelNames: ['status'],
})

export const aiOtelMiddlewareCounter = new Counter({
    name: 'llma_ai_otel_middleware_total',
    help: 'OTel events processed by library middleware',
    labelNames: ['library'],
})

export const aiOtelEventTypeCounter = new Counter({
    name: 'llma_ai_otel_event_type_total',
    help: 'OTel events by type and library',
    labelNames: ['event_type', 'library'],
})

export const aiOtelOlderSpecEventsCounter = new Counter({
    name: 'llma_ai_otel_older_spec_events_total',
    help: 'Outcome of decoding the older OTel GenAI span-events `events` attribute',
    labelNames: ['outcome'],
})

export const aiOtelSystemInstructionsCounter = new Counter({
    name: 'llma_ai_otel_system_instructions_total',
    help: 'Outcome of promoting `gen_ai.system_instructions` into a leading $ai_input system message',
    labelNames: ['outcome'],
})

export const aiOtelGroupsCounter = new Counter({
    name: 'llma_ai_otel_groups_total',
    help: 'Outcome of decoding a string-valued $groups attribute back into an object',
    labelNames: ['outcome'],
})

// The team was renamed from LLMA to AIO: metrics above keep their historical
// `llma_` prefix (dashboards depend on it); new metrics use `aio_` from now on.

export const aiBlobOffloadS3Duration = new Histogram({
    name: 'aio_blob_offload_s3_request_duration_seconds',
    help: 'Latency of S3 requests made by the AI blob offload store',
    labelNames: ['op'],
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
})

export const aiBlobOffloadS3Errors = new Counter({
    name: 'aio_blob_offload_s3_errors_total',
    help: 'S3 request failures in the AI blob offload store',
    labelNames: ['op'],
})

// No team_id labels: AI_BLOB_OFFLOAD_TEAMS accepts '*', and per-team series on these
// happy-path counters would explode at that point. Per-team usage lives in ClickHouse.
export const aiBlobOffloadEventsCounter = new Counter({
    name: 'aio_blob_offload_events_total',
    help: 'AI events scanned by the blob offload step',
    labelNames: ['outcome'], // outcome: no_blobs | offloaded
})

export const aiBlobOffloadBlobsCounter = new Counter({
    name: 'aio_blob_offload_blobs_total',
    help: 'Blobs detected and stored by the offload step',
    labelNames: ['detector', 'mime_family', 'outcome'], // outcome: uploaded | fresh | touched
})

export const aiBlobOffloadBelowFloorCounter = new Counter({
    name: 'aio_blob_offload_below_floor_total',
    help: 'Binary payloads left inline because they are under the size floor',
})

export const aiBlobOffloadBelowFloorBytes = new Counter({
    name: 'aio_blob_offload_below_floor_bytes_total',
    help: 'Estimated decoded bytes of binary payloads left inline under the size floor',
})

export const aiBlobOffloadBlobBytes = new Histogram({
    name: 'aio_blob_offload_blob_bytes',
    help: 'Decoded size of offloaded blobs',
    labelNames: ['mime_family'],
    buckets: [1024, 8192, 65536, 262144, 1048576, 4194304, 8388608],
})

export const aiBlobOffloadBlobsPerEvent = new Histogram({
    name: 'aio_blob_offload_blobs_per_event',
    help: 'Unique blobs per offloaded event',
    buckets: [1, 2, 3, 5, 8, 13, 21],
})

// Row sizes after rewrite: kafka_producer_message_size_bytes{topic_name=<ai_events topic>}.
export const aiBlobOffloadEventBytesSaved = new Histogram({
    name: 'aio_blob_offload_event_bytes_saved',
    help: 'Serialized bytes removed per offloaded event by rewriting payloads to pointers',
    buckets: [4096, 65536, 262144, 1048576, 2097152, 4194304, 8388608],
})
