import { runInstrumentedFunction } from '../../../main/utils'
import { Action, Element, IngestionEvent, Person } from '../../../types'
import { convertToProcessedPluginEvent } from '../../../utils/event'
import { runOnAction, runOnEvent } from '../../plugins/run'
import { EventPipelineRunner, StepResult } from './runner'

export async function runAsyncHandlersStep(
    runner: EventPipelineRunner,
    event: IngestionEvent,
    person: Person | undefined
): Promise<StepResult> {
    if (runner.hub.capabilities.processAsyncHandlers) {
        await Promise.all([
            processOnEvent(runner, event),
            processOnActionAndWebhooks(runner, event, person, event.elementsList),
        ])
    }

    return null
}

async function processOnEvent(runner: EventPipelineRunner, event: IngestionEvent) {
    const processedPluginEvent = convertToProcessedPluginEvent(event)
    const isSnapshot = event.event === '$snapshot'

    await runInstrumentedFunction({
        server: runner.hub,
        event: processedPluginEvent,
        func: (event) => runOnEvent(runner.hub, event),
        statsKey: `kafka_queue.single_on_${isSnapshot ? 'snapshot' : 'event'}`,
        timeoutMessage: `After 30 seconds still running on${isSnapshot ? 'Snapshot' : 'Event'}`,
    })
}

async function processOnActionAndWebhooks(
    runner: EventPipelineRunner,
    event: IngestionEvent,
    person: Person | undefined,
    elements: Element[] | undefined
) {
    const promises = []
    let actionMatches: Action[] = []
    const processedPluginEvent = convertToProcessedPluginEvent(event)

    if (event.event !== '$snapshot') {
        actionMatches = await runner.hub.actionMatcher.match(event, person, elements)
        promises.push(runner.hub.hookCannon.findAndFireHooks(event, person, actionMatches))
    }

    for (const actionMatch of actionMatches) {
        promises.push(
            runInstrumentedFunction({
                server: runner.hub,
                event: processedPluginEvent,
                func: (event) => runOnAction(runner.hub, actionMatch, event),
                statsKey: `kafka_queue.on_action`,
                timeoutMessage: 'After 30 seconds still running onAction',
            })
        )
    }

    await Promise.all(promises)
}
