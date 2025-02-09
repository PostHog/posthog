import { Message } from 'node-rdkafka'

import { PipelineEvent, Team } from '../types'

export type TokenDistinctId = string & { __brand: 'TokenDistinctId' }
export type IncomingEvent = { message: Message; event: PipelineEvent }

export type IncomingEventsByTokenDistinctId = {
    [key: TokenDistinctId]: IncomingEvent[]
}

export type EventIngestionBatchContext = {
    // A context object usable by the event pipeline runner
    eventsByTokenDistinctId: IncomingEventsByTokenDistinctId
    teamsByToken: Record<string, Team | null>
}
