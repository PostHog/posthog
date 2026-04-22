import { Counter } from 'prom-client'

export const eventFiltersEventsEvaluated = new Counter({
    name: 'ingestion_filters_events_evaluated',
    help: 'Total number of events evaluated by event filters',
    labelNames: ['outcome'],
})
