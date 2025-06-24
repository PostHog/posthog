import { PluginEvent } from '@posthog/plugin-scaffold'

import { HogTransformerService, TransformationResult } from '../../../cdp/hog-transformations/hog-transformer.service'
import { droppedEventCounter } from './metrics'
export async function transformEventStep(
    event: PluginEvent,
    hogTransformer: HogTransformerService | null
): Promise<TransformationResult> {
    if (!hogTransformer) {
        return { event, invocationResults: [] }
    }
    const result = await hogTransformer.transformEventAndProduceMessages(event)
    if (!result.event) {
        droppedEventCounter.inc()
    }
    return result
}
