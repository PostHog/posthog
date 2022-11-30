import { runInstrumentedFunction } from '../../../main/utils'
import { Element, PostIngestionEvent } from '../../../types'
import { convertToProcessedPluginEvent } from '../../../utils/event'
import { runOnEvent, runOnSnapshot } from '../../plugins/run'
import { LazyPersonContainer } from '../lazy-person-container'
import { EventPipelineRunner, StepResult } from './runner'

export async function runAsyncHandlersStep(
    runner: EventPipelineRunner,
    event: PostIngestionEvent,
    personContainer: LazyPersonContainer
): Promise<StepResult> {
    await Promise.all([
        processOnEvent(runner, event),
        processWebhooks(runner, event, personContainer, event.elementsList),
    ])

    return null
}

async function processOnEvent(runner: EventPipelineRunner, event: PostIngestionEvent) {
    const processedPluginEvent = convertToProcessedPluginEvent(event)
    const isSnapshot = event.event === '$snapshot'
    const method = isSnapshot ? runOnSnapshot : runOnEvent

    await runInstrumentedFunction({
        server: runner.hub,
        event: processedPluginEvent,
        func: (event) => method(runner.hub, event),
        statsKey: `kafka_queue.single_${isSnapshot ? 'on_snapshot' : 'on_event'}`,
        timeoutMessage: `After 30 seconds still running ${isSnapshot ? 'onSnapshot' : 'onEvent'}`,
    })
}

async function processWebhooks(
    runner: EventPipelineRunner,
    event: PostIngestionEvent,
    personContainer: LazyPersonContainer,
    elements: Element[] | undefined
) {
    if (event.event !== '$snapshot') {
        const person = await personContainer.get()
        const actionMatches = await runner.hub.actionMatcher.match(event, person, elements)
        await runner.hub.hookCannon.findAndFireHooks(event, person, actionMatches)
    }
}
