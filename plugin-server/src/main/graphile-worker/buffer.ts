import { PluginEvent } from '@posthog/plugin-scaffold'
import { Hub } from 'types'

import { workerTasks } from '../../worker/tasks'

export function runBufferEventPipeline(hub: Hub, event: PluginEvent): Promise<void> {
    hub.lastActivity = new Date().valueOf()
    hub.lastActivityType = 'runBufferEventPipeline'
    return workerTasks['runBufferEventPipeline'](hub, { event })
}
