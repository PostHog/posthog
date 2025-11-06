import { EventHeaders, Hub, IncomingEventWithTeam } from '../../types'
import { PipelineResult, isOkResult, ok } from '../pipelines/results'

export function createApplyCookielessProcessingStep<
    T extends { eventWithTeam: IncomingEventWithTeam; headers: EventHeaders },
>(hub: Hub) {
    return async function applyCookielessProcessingStep(events: T[]): Promise<PipelineResult<T>[]> {
        const cookielessResults = await hub.cookielessManager.doBatch(events.map((x) => x.eventWithTeam))

        return events.map((event, index) => {
            const cookielessResult = cookielessResults[index]

            if (isOkResult(cookielessResult)) {
                return ok({
                    ...event,
                    eventWithTeam: cookielessResult.value,
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
