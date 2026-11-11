import { Message } from 'node-rdkafka'

import { PipelineResult, isOkResult, ok } from '@posthog/ingestion-common/framework/results'
import { PluginEvent } from '@posthog/node-common/plugin-scaffold'

import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventHeaders, Team } from '~/types'

type ApplyCookielessProcessingInput = { event: PluginEvent; team: Team; message: Message; headers: EventHeaders }

export function createApplyCookielessProcessingStep<T extends ApplyCookielessProcessingInput>(
    cookielessManager: CookielessManager
) {
    return async function applyCookielessProcessingStep(events: T[]): Promise<PipelineResult<T>[]> {
        const cookielessResults = await cookielessManager.doBatch(events)

        return events.map((event, index) => {
            const cookielessResult = cookielessResults[index]

            if (isOkResult(cookielessResult)) {
                return ok({
                    ...event,
                    event: cookielessResult.value.event,
                })
            } else {
                // Return the drop/dlq/redirect result from cookieless processing
                return cookielessResult
            }
        })
    }
}
