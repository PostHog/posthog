import { HogTransformerService, TransformationResult } from '~/cdp/hog-transformations/hog-transformer.service'
import { PluginEvent } from '~/plugin-scaffold'

export async function transformEventStep(
    event: PluginEvent,
    hogTransformer: HogTransformerService | null
): Promise<TransformationResult> {
    if (!hogTransformer) {
        return { event, invocationResults: [] }
    }
    return await hogTransformer.transformEventAndProduceMessages(event)
}
