import { Counter } from 'prom-client'

export const eventFiltersEventsEvaluated = new Counter({
    name: 'ingestion_filters_events_evaluated',
    help: 'Total number of events evaluated by event filters',
    labelNames: ['outcome'],
})

export const eventFiltersRefreshErrors = new Counter({
    name: 'ingestion_filters_refresh_errors',
    help: 'Number of failed background reloads of event filter config',
})

export const eventFiltersOverrideRefreshErrors = new Counter({
    name: 'ingestion_filters_override_refresh_errors',
    help: 'Number of failed background reloads of event filter pipeline overrides',
})
