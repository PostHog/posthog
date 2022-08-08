import { runInstrumentedFunction } from '../../../main/utils'
import { Action, Element, IngestionEvent } from '../../../types'
import { convertToProcessedPluginEvent } from '../../../utils/event'
import { runOnEvent, runOnSnapshot } from '../../plugins/run'
import { LazyPersonContainer } from '../lazy-person-container'
import { EventPipelineRunner, StepResult } from './runner'

export async function runAsyncHandlersStep(
    runner: EventPipelineRunner,
    event: IngestionEvent,
    personContainer: LazyPersonContainer
): Promise<StepResult> {
    if (runner.hub.capabilities.processAsyncHandlers) {
        await Promise.all([
            processOnEvent(runner, event),
            processWebhooks(runner, event, personContainer, event.elementsList),
        ])
    }

    return null
}

async function processOnEvent(runner: EventPipelineRunner, event: IngestionEvent) {
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
    event: IngestionEvent,
    personContainer: LazyPersonContainer,
    elements: Element[] | undefined
) {
    let actionMatches: Action[] = []

    if (event.event !== '$snapshot') {
        actionMatches = await runner.hub.actionMatcher.match(event, personContainer, elements)
        await runner.hub.hookCannon.findAndFireHooks(event, personContainer, actionMatches)
    }
}
