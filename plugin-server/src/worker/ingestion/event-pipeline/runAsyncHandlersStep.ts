import { runInstrumentedFunction } from '../../../main/utils'
import { Element, PostIngestionEvent } from '../../../types'
import { convertToProcessedPluginEvent } from '../../../utils/event'
import { runOnEvent } from '../../plugins/run'
import { EventPipelineRunner } from './runner'

export async function runAsyncHandlersStep(runner: EventPipelineRunner, event: PostIngestionEvent) {
    await Promise.all([processOnEvent(runner, event), processWebhooks(runner, event, event.elementsList)])

    return null
}

async function processOnEvent(runner: EventPipelineRunner, event: PostIngestionEvent) {
    const processedPluginEvent = convertToProcessedPluginEvent(event)

    await runInstrumentedFunction({
        server: runner.hub,
        event: processedPluginEvent,
        func: (event) => runOnEvent(runner.hub, event),
        statsKey: `kafka_queue.single_on_event`,
        timeoutMessage: `After 30 seconds still running onEvent`,
        teamId: event.teamId,
    })
}

async function processWebhooks(
    runner: EventPipelineRunner,
    event: PostIngestionEvent,
    elements: Element[] | undefined
) {
    const actionMatches = await runner.hub.actionMatcher.match(event, elements)
    await runner.hub.hookCannon.findAndFireHooks(event, actionMatches)
}
