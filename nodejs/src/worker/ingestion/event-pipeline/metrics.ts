import { Counter, Summary } from 'prom-client'

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
    labelNames: ['result', 'step_name', 'details'],
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
