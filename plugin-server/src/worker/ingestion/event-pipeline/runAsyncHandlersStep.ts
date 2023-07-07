import { runInstrumentedFunction } from '../../../main/utils'
import { PostIngestionEvent } from '../../../types'
import { convertToProcessedPluginEvent } from '../../../utils/event'
import { runOnEvent } from '../../plugins/run'
import { EventPipelineRunner } from './runner'

export async function processOnEventStep(runner: EventPipelineRunner, event: PostIngestionEvent) {
    const processedPluginEvent = convertToProcessedPluginEvent(event)

    await runInstrumentedFunction({
        server: runner.hub,
        event: processedPluginEvent,
        func: (event) => runOnEvent(runner.hub, event),
        statsKey: `kafka_queue.single_on_event`,
        timeoutMessage: `After 30 seconds still running onEvent`,
        teamId: event.teamId,
    })
    return null
}

export async function processWebhooksStep(runner: EventPipelineRunner, event: PostIngestionEvent) {
    const elements = event.elementsList
    const actionMatches = await runner.hub.actionMatcher.match(event, elements)
    await runner.hub.hookCannon.findAndFireHooks(event, actionMatches)
    return null
}
