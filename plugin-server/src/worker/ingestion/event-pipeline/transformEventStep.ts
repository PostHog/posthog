import { PluginEvent } from '@posthog/plugin-scaffold'

import { HogTransformerService, TransformationResult } from '../../../cdp/hog-transformations/hog-transformer.service'
import { HogFunctionType } from '../../../cdp/types'
import { droppedEventCounter } from './metrics'
export async function transformEventStep(
    event: PluginEvent,
    hogTransformer: HogTransformerService | null,
    teamHogFunctions: HogFunctionType[]
): Promise<TransformationResult> {
    if (!hogTransformer) {
        return { event, invocationResults: [], messagePromises: [], watcherPromises: [] }
    }
    const result = await hogTransformer.transformEventAndProduceMessages(event, teamHogFunctions)
    if (!result.event) {
        droppedEventCounter.inc()
    }
    return result
}
