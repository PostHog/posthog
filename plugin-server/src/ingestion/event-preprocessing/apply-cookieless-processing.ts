import { Hub, IncomingEventWithTeam } from '../../types'
import { isSuccessResult, success } from '../../worker/ingestion/event-pipeline/pipeline-step-result'
import { BatchProcessingResult } from '../batch-processing-pipeline'

export function createApplyCookielessProcessingStep<T extends { eventWithTeam: IncomingEventWithTeam }>(hub: Hub) {
    return async (events: T[]): Promise<BatchProcessingResult<T>> => {
        const cookielessResults = await hub.cookielessManager.doBatch(events.map((x) => x.eventWithTeam))

        return events.map((event, index) => {
            const cookielessResult = cookielessResults[index]

            if (isSuccessResult(cookielessResult)) {
                return success({
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
