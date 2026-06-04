import { Counter, Histogram, Summary } from 'prom-client'

export const pipelineStepErrorCounter = new Counter({
    name: 'events_pipeline_step_error_total',
    help: 'Number of events that have errored in the step',
    labelNames: ['step_name'],
})
export const pipelineStepStalledCounter = new Counter({
    name: 'events_pipeline_step_stalled_total',
    help: 'Number of events that have stalled in the step',
    labelNames: ['step_name'],
})
export const pipelineStepMsSummary = new Summary({
    name: 'events_pipeline_step_ms',
    help: 'Duration spent in each step',
    percentiles: [0.5, 0.9, 0.95, 0.99],
    labelNames: ['step_name'],
})
export const pipelineStepThrowCounter = new Counter({
    name: 'events_pipeline_step_throw_total',
    help: 'Number of events that have thrown error in the step',
    labelNames: ['step_name'],
})
export const eventProcessedAndIngestedCounter = new Counter({
    name: 'event_processed_and_ingested',
    help: 'Count of events processed and ingested',
})

export const ingestionPipelineResultCounter = new Counter({
    name: 'ingestion_pipeline_results',
    help: 'Count of pipeline results by type',
    labelNames: ['result', 'last_step_name', 'details'],
})

export const invalidTimestampCounter = new Counter({
    name: 'invalid_timestamp_total',
    help: 'Count of events with invalid timestamp',
    labelNames: ['type'],
})

export const tokenOrTeamPresentCounter = new Counter({
    name: 'ingestion_event_hasauthinfo_total',
    help: 'Count of events by presence of the team_id and token field.',
    labelNames: ['team_id_present', 'token_present'],
})

export const droppedBloatPropertyCounter = new Counter({
    name: 'ingestion_dropped_bloat_property_total',
    help: 'Count of deprecated posthog-js persistence-cache properties stripped from event payloads before ClickHouse write (see strip-bloat-properties.ts BLOAT_PROPERTIES).',
    labelNames: ['property'],
})

export const strippedFeatureFlagCalledPropertyCounter = new Counter({
    name: 'ingestion_stripped_feature_flag_called_property_total',
    help: 'Count of non-whitelisted properties stripped from $feature_flag_called events before ClickHouse write (see strip-bloat-properties.ts FEATURE_FLAG_CALLED_KEEP). Unlabelled: stripped key names are user-controlled and would create unbounded Prometheus label cardinality.',
})

export const featureFlagCalledPropertyCountHistogram = new Histogram({
    name: 'ingestion_feature_flag_called_property_count',
    help: 'Number of properties present on a $feature_flag_called event before stripping. Surfaces property-count outliers driving per-event strip cost (see strip-bloat-properties.ts stripFeatureFlagCalledProperties).',
    buckets: [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, Infinity],
})

export const featureFlagCalledStripOutcomeCounter = new Counter({
    name: 'ingestion_feature_flag_called_strip_outcome_total',
    help: 'Per-event outcome of $feature_flag_called property stripping. outcome="stripped" when the allowlist strip ran; outcome="kept_multivariate" when stripping was skipped because $feature_flag_response is a variant string (a potential experiment exposure, see strip-bloat-properties.ts).',
    labelNames: ['outcome'],
})
