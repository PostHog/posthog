import { PluginEvent } from '@posthog/plugin-scaffold'

import { HogTransformerService, TransformationResult } from '../../../cdp/hog-transformations/hog-transformer.service'

export async function transformEventStep(
    event: PluginEvent,
    hogTransformer: HogTransformerService | null
): Promise<TransformationResult> {
    if (!hogTransformer) {
        return { event, messagePromises: [] }
    }
    return hogTransformer.transformEvent(event)
}
