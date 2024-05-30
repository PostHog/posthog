import { runInstrumentedFunction } from '../../../main/utils'
import { Hub, PostIngestionEvent } from '../../../types'
import { runComposeWebhook, runOnEvent } from '../../plugins/run'
import { ActionMatcher } from '../action-matcher'
import { HookCommander, instrumentWebhookStep } from '../hooks'

export async function processOnEventStep(hub: Hub, event: PostIngestionEvent) {
    await runInstrumentedFunction({
        timeoutContext: () => ({
            team_id: event.teamId,
            event_uuid: event.eventUuid,
        }),
        func: () => runOnEvent(hub, event),
        statsKey: `kafka_queue.single_on_event`,
        timeoutMessage: `After 30 seconds still running onEvent`,
        teamId: event.teamId,
    })
    return null
}

export async function processComposeWebhookStep(hub: Hub, event: PostIngestionEvent) {
    await runInstrumentedFunction({
        timeoutContext: () => ({
            team_id: event.teamId,
            event_uuid: event.eventUuid,
        }),
        func: () => runComposeWebhook(hub, event),
        statsKey: `kafka_queue.single_compose_webhook`,
        timeoutMessage: `After 30 seconds still running composeWebhook`,
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
        return await actionMatcher.match(event)
    })
    await instrumentWebhookStep('findAndfireHooks', async () => {
        await hookCannon.findAndFireHooks(event, actionMatches)
    })
    return null
}
