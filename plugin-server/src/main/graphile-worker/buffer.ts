import { PluginEvent } from '@posthog/plugin-scaffold'
import { Hub } from 'types'

import Piscina from '../../worker/piscina'

export function runBufferEventPipeline(hub: Hub, piscina: Piscina, event: PluginEvent): Promise<void> {
    hub.lastActivity = new Date().valueOf()
    hub.lastActivityType = 'runBufferEventPipeline'
    return piscina.run({ task: 'runBufferEventPipeline', args: { event } })
}
