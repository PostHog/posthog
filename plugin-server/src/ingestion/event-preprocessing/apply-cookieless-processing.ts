import { IncomingEventWithTeam } from '../../types'
import { CookielessManager } from '../cookieless/cookieless-manager'
import { PipelineResult, isOkResult, ok } from '../pipelines/results'

type ApplyCookielessProcessingInput = { eventWithTeam: IncomingEventWithTeam }
type ApplyCookielessProcessingOutput = { eventWithTeam: IncomingEventWithTeam }

export function createApplyCookielessProcessingStep<T extends ApplyCookielessProcessingInput>(
    cookielessManager: CookielessManager
) {
    return async function applyCookielessProcessingStep(
        events: T[]
    ): Promise<PipelineResult<T & ApplyCookielessProcessingOutput>[]> {
        const cookielessResults = await cookielessManager.doBatch(events.map((x) => x.eventWithTeam))

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
