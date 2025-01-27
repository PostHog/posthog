import { PluginEvent } from '@posthog/plugin-scaffold'

import { HogTransformerService } from '../../../cdp/hog-transformations/hog-transformer.service'
import { Hub } from '../../../types'

// TODO: THIS IS THE REST OF THE PLAN
// 1. we need logs and these things and we do not want them to block the main thread so avoid async if possible
// 2. logs and metrics should be published to a list of promises and then await the whole promise batch
// 3. in case people transform stuff we do not support do we drop the event or just return the event with the allowed modifications?
// 4. we need to support ordering of transformations e.g. if someone has 3 transformations and the first one fails we want to run the other 2 (are they dependend on each other?)

export async function transformEventStep(hub: Hub, event: PluginEvent): Promise<PluginEvent> {
    if (!hub.HOG_TRANSFORMATIONS_ENABLED) {
        return event
    }

    // Lazy initialize the transformer when needed
    let hogTransformer = hub.hogTransformer
    if (!hogTransformer) {
        hogTransformer = new HogTransformerService(hub)
        await hogTransformer.start()
        hub.hogTransformer = hogTransformer
    }

    return await hogTransformer.transformEvent(event)
}
