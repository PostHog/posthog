import { runInstrumentedFunction } from '../../../main/utils'
import { PostIngestionEvent } from '../../../types'
import { convertToProcessedPluginEvent } from '../../../utils/event'
import { runOnEvent } from '../../plugins/run'
import { ActionMatcher } from '../action-matcher'
import { HookCommander } from '../hooks'
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

export async function processWebhooksStep(
    event: PostIngestionEvent,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander
) {
    const elements = event.elementsList
    const actionMatches = await actionMatcher.match(event, elements)
    await hookCannon.findAndFireHooks(event, actionMatches)
    return null
}
