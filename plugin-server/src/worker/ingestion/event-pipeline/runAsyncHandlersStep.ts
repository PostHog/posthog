import { runInstrumentedFunction } from '../../../main/utils'
import { Element, PostIngestionEvent } from '../../../types'
import { convertToProcessedPluginEvent } from '../../../utils/event'
import { runOnEvent } from '../../plugins/run'
import { LazyPersonContainer } from '../lazy-person-container'
import { EventPipelineRunner } from './runner'

export async function runAsyncHandlersStep(
    runner: EventPipelineRunner,
    event: PostIngestionEvent,
    personContainer: LazyPersonContainer
) {
    await Promise.all([
        processOnEvent(runner, event),
        processWebhooks(runner, event, personContainer, event.elementsList),
    ])

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
    })
}

async function processWebhooks(
    runner: EventPipelineRunner,
    event: PostIngestionEvent,
    personContainer: LazyPersonContainer,
    elements: Element[] | undefined
) {
    const person = await personContainer.get()
    const actionMatches = await runner.hub.actionMatcher.match(event, person, elements)
    await runner.hub.hookCannon.findAndFireHooks(event, person, actionMatches)
}
