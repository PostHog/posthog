import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub } from '~/src/types'

export async function cookielessServerHashStep(hub: Hub, event: PluginEvent): Promise<[PluginEvent | undefined]> {
    const processedEvent = await hub.cookielessManager.processEvent(event)
    return [processedEvent]
}
