import { runInstrumentedFunction } from '../../../main/utils'
import { Hub, PostIngestionEvent } from '../../../types'
import { convertToProcessedPluginEvent } from '../../../utils/event'
import { runOnEvent } from '../../plugins/run'
import { EventPipelineRunner } from './runner'

export async function processOnEventStep(runner: EventPipelineRunner, event: PostIngestionEvent) {
    const processedPluginEvent = convertToProcessedPluginEvent(event)

    await runInstrumentedFunction({
        event: processedPluginEvent,
        func: (event) => runOnEvent(runner.hub, event),
        statsKey: `kafka_queue.single_on_event`,
        timeoutMessage: `After 30 seconds still running onEvent`,
        teamId: event.teamId,
    })
    return null
}

export async function processWebhooksStep(hub: Hub, event: PostIngestionEvent) {
    const elements = event.elementsList
    const actionMatches = await hub.actionMatcher.match(event, elements)
    await hub.hookCannon.findAndFireHooks(event, actionMatches)
    return null
}
