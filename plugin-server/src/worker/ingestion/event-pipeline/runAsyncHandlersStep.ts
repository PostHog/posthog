import { instrumentFn } from '~/common/tracing/tracing-utils'

import { Hub, PostIngestionEvent } from '../../../types'
import { runComposeWebhook } from '../../plugins/run'
import { ActionMatcher } from '../action-matcher'
import { HookCommander, instrumentWebhookStep } from '../hooks'

export async function processComposeWebhookStep(hub: Hub, event: PostIngestionEvent): Promise<void> {
    await instrumentFn(
        {
            getLoggingContext: () => ({
                team_id: event.teamId,
                event_uuid: event.eventUuid,
            }),
            key: `kafka_queue.single_compose_webhook`,
        },
        () => runComposeWebhook(hub, event)
    )
}

export async function processWebhooksStep(
    event: PostIngestionEvent,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander
): Promise<void> {
    const actionMatches = actionMatcher.match(event)
    await instrumentWebhookStep('findAndfireHooks', async () => {
        await hookCannon.findAndFireHooks(event, actionMatches)
    })
}
