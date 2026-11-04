import { HogFlow } from '../schema/hogflow'
import { HogFunctionType, MinimalAppMetric } from '../types'
import { eventNamePassesPreFilter, preFiltersOnEventName } from '../utils/hog-function-filtering'

export const runsOnEvents = (fn: HogFunctionType): boolean => (fn.filters?.source ?? 'events') === 'events'

export const triggersOnEvents = (
    flow: HogFlow
): flow is HogFlow & { trigger: Extract<HogFlow['trigger'], { type: 'event' }> } => flow.trigger.type === 'event'

export type EventNameGate = {
    admits: (eventName: string) => boolean
    /** The metrics the pre-filter records for an event no source admits, so skipping it records the same. */
    filteredMetrics: () => { hogFunctions: MinimalAppMetric[]; hogFlows: MinimalAppMetric[] }
}

const filtered = (teamId: number, sourceId: string): MinimalAppMetric => ({
    team_id: teamId,
    app_source_id: sourceId,
    metric_kind: 'other',
    metric_name: 'filtered',
    count: 1,
})

/**
 * Decides from the event name alone whether any event destination or event-triggered flow of a team
 * could want an event, by the same pre-filter that rejects it today once the body is parsed.
 */
export function buildEventNameGate({
    hogFunctions,
    hogFlows,
    alsoAdmitted,
}: {
    hogFunctions: HogFunctionType[]
    hogFlows: HogFlow[]
    alsoAdmitted: string[]
}): EventNameGate {
    const eventFunctions = hogFunctions.filter(runsOnEvents)
    const eventFlows = hogFlows.filter(triggersOnEvents)
    const filters = [...eventFunctions.map((fn) => fn.filters), ...eventFlows.map((flow) => flow.trigger.filters)]

    return {
        admits: (eventName) =>
            alsoAdmitted.includes(eventName) ||
            filters.some((filter) => !preFiltersOnEventName(filter) || eventNamePassesPreFilter(filter, eventName)),
        filteredMetrics: () => ({
            hogFunctions: eventFunctions.map((fn) => filtered(fn.team_id, fn.id)),
            hogFlows: eventFlows.map((flow) => ({
                ...filtered(flow.team_id, flow.id),
                app_source_version: { id: flow.id, version: flow.version },
            })),
        }),
    }
}
