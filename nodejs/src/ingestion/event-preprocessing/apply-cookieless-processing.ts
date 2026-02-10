import { Message } from 'node-rdkafka'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { EventHeaders, Team } from '../../types'
import { CookielessManager } from '../cookieless/cookieless-manager'
import { PipelineResult, isOkResult, ok } from '../pipelines/results'

type ApplyCookielessProcessingInput = { event: PluginEvent; team: Team; message: Message; headers: EventHeaders }

export function createApplyCookielessProcessingStep<T extends ApplyCookielessProcessingInput>(
    cookielessManager: CookielessManager
) {
    return async function applyCookielessProcessingStep(events: T[]): Promise<PipelineResult<T>[]> {
        const cookielessResults = await cookielessManager.doBatch(
            events.map((x) => ({ message: x.message, event: x.event, team: x.team, headers: x.headers }))
        )

        return events.map((input, index) => {
            const cookielessResult = cookielessResults[index]

            if (isOkResult(cookielessResult)) {
                return ok({
                    ...input,
                    event: cookielessResult.value.event as PluginEvent,
                })
            } else {
                // Return the drop/dlq/redirect result from cookieless processing
                return cookielessResult
            }
        })
    }
}
