import { runInstrumentedFunction } from '../../../main/utils'
import { Action, Element, Person, PreIngestionEvent } from '../../../types'
import { convertToProcessedPluginEvent } from '../../../utils/event'
import { runOnAction, runOnEvent, runOnSnapshot } from '../../plugins/run'
import { EventPipelineRunner, StepResult } from './runner'

export async function runAsyncHandlersStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    person: Person | undefined,
    elements: Element[] | undefined
): Promise<StepResult> {
    const promises = []
    let actionMatches: Action[] = []
    if (event.event !== '$snapshot') {
        actionMatches = await runner.hub.actionMatcher.match(event, person, elements)
        promises.push(runner.hub.hookCannon.findAndFireHooks(event, person, event.siteUrl, actionMatches))
    }

    const processedPluginEvent = convertToProcessedPluginEvent(event)
    const isSnapshot = event.event === '$snapshot'
    const method = isSnapshot ? runOnSnapshot : runOnEvent
    promises.push(
        runInstrumentedFunction({
            server: runner.hub,
            event: processedPluginEvent,
            func: (event) => method(runner.hub, event),
            statsKey: `kafka_queue.single_${isSnapshot ? 'on_snapshot' : 'on_event'}`,
            timeoutMessage: `After 30 seconds still running ${isSnapshot ? 'onSnapshot' : 'onEvent'}`,
        })
    )
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

    return null
}
