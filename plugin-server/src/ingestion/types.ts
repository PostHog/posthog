import { PluginEvent } from '@posthog/plugin-scaffold'
import { Message } from 'node-rdkafka'

import { Person, PipelineEvent, Team } from '../types'

export type TokenDistinctId = string & { __brand: 'TokenDistinctId' }
export type IncomingEvent = { message: Message; event: PipelineEvent }

export type IncomingEventsByTokenDistinctId = {
    [key: TokenDistinctId]: IncomingEvent[]
}

export type EventIngestionBatchContext = {
    // TODO: Add teams to this context to reduce team loading
    // The state of a given batch of events. This can be passed around so that subclasses can modify the state with only the final runner executing the changes
    eventsByTokenDistinctId: IncomingEventsByTokenDistinctId
    personsByTokenDistinctId: Record<TokenDistinctId, Person>
    personlessDistinctIdsByTokenDistinctId: Record<TokenDistinctId, 'none' | 'is_merged' | 'identified'>
    teamsByTokenDistinctId: Record<string, Team>

    // Outcomes
    results: {
        events: PluginEvent[]
        ingestionWarnings: any[]
        persons: Person[]
    }
}
