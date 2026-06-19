import { HogTransformationResult, HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { PluginEvent } from '~/plugin-scaffold'

export async function transformEventStep(
    event: PluginEvent,
    hogTransformer: HogTransformer | null
): Promise<HogTransformationResult> {
    if (!hogTransformer) {
        return { event, invocationResults: [] }
    }
    return await hogTransformer.transformEventAndProduceMessages(event)
}
