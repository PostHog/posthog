import { runInstrumentedFunction } from '../../../main/utils'
import { Hub, PostIngestionEvent } from '../../../types'
import { convertToProcessedPluginEvent } from '../../../utils/event'
import { runOnEvent } from '../../plugins/run'
import { ActionMatcher } from '../action-matcher'
import { HookCommander, instrumentWebhookStep } from '../hooks'

export async function processOnEventStep(hub: Hub, event: PostIngestionEvent) {
    const processedPluginEvent = convertToProcessedPluginEvent(event)

    await runInstrumentedFunction({
        timeoutContext: () => ({
            team_id: event.teamId,
            event_uuid: event.eventUuid,
        }),
        func: () => runOnEvent(hub, processedPluginEvent),
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
    const actionMatches = await instrumentWebhookStep('actionMatching', async () => {
        const elements = event.elementsList
        return await actionMatcher.match(event, elements)
    })
    await instrumentWebhookStep('findAndfireHooks', async () => {
        await hookCannon.findAndFireHooks(event, actionMatches)
    })
    return null
}
