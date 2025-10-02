import { Counter, Summary } from 'prom-client'

export const pipelineLastStepCounter = new Counter({
    name: 'events_pipeline_last_step_total',
    help: 'Number of events that have entered the last step',
    labelNames: ['step_name'],
})
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
export const pipelineStepDLQCounter = new Counter({
    name: 'events_pipeline_step_dlq_total',
    help: 'Number of events that have been sent to DLQ in the step',
    labelNames: ['step_name'],
})

export const eventProcessedAndIngestedCounter = new Counter({
    name: 'event_processed_and_ingested',
    help: 'Count of events processed and ingested',
})

export const invalidTimestampCounter = new Counter({
    name: 'invalid_timestamp_total',
    help: 'Count of events with invalid timestamp',
    labelNames: ['type'],
})

export const droppedEventCounter = new Counter({
    name: 'event_pipeline_dropped_events_total',
    help: 'Count of events dropped by plugin server',
})

export const tokenOrTeamPresentCounter = new Counter({
    name: 'ingestion_event_hasauthinfo_total',
    help: 'Count of events by presence of the team_id and token field.',
    labelNames: ['team_id_present', 'token_present'],
})

export const pipelineStepRedirectCounter = new Counter({
    name: 'events_pipeline_step_redirect_total',
    help: 'Number of events that have been redirected in the step',
    labelNames: ['step_name', 'target_topic', 'preserve_key'],
})
