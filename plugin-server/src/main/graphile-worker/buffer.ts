import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold'
import { Hub } from 'types'

import { EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'

export async function runBufferEventPipeline(hub: Hub, piscina: Piscina, event: PluginEvent): Promise<void> {
    hub.lastActivity = new Date().valueOf()
    hub.lastActivityType = 'runBufferEventPipeline'
    const runner = new EventPipelineRunner(hub, piscina, event)
    await runner.runBufferEventPipeline(event)
}
