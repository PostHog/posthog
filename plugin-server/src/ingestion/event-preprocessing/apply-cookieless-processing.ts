import { Message } from 'node-rdkafka'

import { EventHeaders, Hub, IncomingEventWithTeam, PipelineEvent, Team } from '../../types'
import { PipelineResult, isOkResult, ok } from '../pipelines/results'

export function createApplyCookielessProcessingStep<
    T extends { message: Message; event: PipelineEvent; headers: EventHeaders; team: Team },
>(hub: Hub) {
    return async function applyCookielessProcessingStep(events: T[]): Promise<PipelineResult<T>[]> {
        // Reconstruct IncomingEventWithTeam for cookieless manager
        const eventsWithTeam: IncomingEventWithTeam[] = events.map((x) => ({
            message: x.message,
            event: x.event,
            headers: x.headers,
            team: x.team,
        }))

        const cookielessResults = await hub.cookielessManager.doBatch(eventsWithTeam)

        return events.map((event, index) => {
            const cookielessResult = cookielessResults[index]

            if (isOkResult(cookielessResult)) {
                return ok({
                    ...event,
                    event: cookielessResult.value.event,
                    headers: {
                        ...event.headers,
                        distinct_id: cookielessResult.value.event.distinct_id,
                    },
                })
            } else {
                // Return the drop/dlq/redirect result from cookieless processing
                return cookielessResult
            }
        })
    }
}
