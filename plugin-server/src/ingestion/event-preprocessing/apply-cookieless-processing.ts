import { Hub, IncomingEventWithTeam } from '../../types'
import { PipelineResult, isOkResult, ok } from '../pipelines/results'

type ApplyCookielessProcessingInput = { eventWithTeam: IncomingEventWithTeam }
type ApplyCookielessProcessingOutput = { eventWithTeam: IncomingEventWithTeam }

export function createApplyCookielessProcessingStep<T extends ApplyCookielessProcessingInput>(hub: Hub) {
    return async function applyCookielessProcessingStep(
        events: T[]
    ): Promise<PipelineResult<T & ApplyCookielessProcessingOutput>[]> {
        const cookielessResults = await hub.cookielessManager.doBatch(events.map((x) => x.eventWithTeam))

        return events.map((event, index) => {
            const cookielessResult = cookielessResults[index]

            if (isOkResult(cookielessResult)) {
                return ok({
                    ...event,
                    eventWithTeam: cookielessResult.value,
                })
            } else {
                // Return the drop/dlq/redirect result from cookieless processing
                return cookielessResult
            }
        })
    }
}
