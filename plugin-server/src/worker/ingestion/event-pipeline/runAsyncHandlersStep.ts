import { runInstrumentedFunction } from '../../../main/utils'
import { Hub, PostIngestionEvent } from '../../../types'
import { runComposeWebhook, runOnEvent } from '../../plugins/run'

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
