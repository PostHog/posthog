import { PluginEvent } from '@posthog/plugin-scaffold'

import { HogTransformerService } from '../../../cdp/hog-transformations/hog-transformer.service'

// TODO: THIS IS THE REST OF THE PLAN
// 1. we need logs and these things and we do not want them to block the main thread so avoid async if possible
// 2. logs and metrics should be published to a list of promises and then await the whole promise batch
// 3. in case people transform stuff we do not support do we drop the event or just return the event with the allowed modifications?
// 4. we need to support ordering of transformations e.g. if someone has 3 transformations and the first one fails we want to run the other 2 (are they dependend on each other?)

export async function transformEventStep(
    event: PluginEvent,
    hogTransformer: HogTransformerService | null
): Promise<PluginEvent> {
    if (!hogTransformer) {
        return event
    }
    return hogTransformer.transformEvent(event)
}
