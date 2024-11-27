import { Message } from 'node-rdkafka'

import { Hub, PostIngestionEvent, RawKafkaEvent } from '../../../types'
import { convertToPostIngestionEvent } from '../../../utils/event'
import {
    processComposeWebhookStep,
    processOnEventStep,
} from '../../../worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { runInstrumentedFunction } from '../../utils'
import { IngestionConsumer } from '../kafka-queue'
import { eventDroppedCounter } from '../metrics'
import { eachBatchHandlerHelper } from './each-batch-webhooks'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export async function handleOnEventPlugins(event: PostIngestionEvent, hub: Hub): Promise<void> {
    await runInstrumentedFunction({
        func: () => processOnEventStep(hub, event),
        statsKey: `kafka_queue.process_async_handlers_on_event`,
        timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
        timeoutContext: () => ({
            event: JSON.stringify(event),
        }),
        teamId: event.teamId,
    })
}

export async function handleComposeWebhookPlugins(event: PostIngestionEvent, hub: Hub): Promise<void> {
    await runInstrumentedFunction({
        func: () => processComposeWebhookStep(hub, event),
        statsKey: `kafka_queue.process_async_handlers_on_event`,
        timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
        timeoutContext: () => ({
            event: JSON.stringify(event),
        }),
        teamId: event.teamId,
    })
}

export async function eachMessageAppsOnEventHandlers(clickHouseEvent: RawKafkaEvent, hub: Hub): Promise<void> {
    const pluginConfigs = hub.pluginConfigsPerTeam.get(clickHouseEvent.team_id)
    if (pluginConfigs) {
        const event = convertToPostIngestionEvent(clickHouseEvent)
        await Promise.all([handleOnEventPlugins(event, hub), handleComposeWebhookPlugins(event, hub)])
    } else {
        eventDroppedCounter
            .labels({
                event_type: 'onevent',
                drop_cause: 'no_matching_plugin',
            })
            .inc()
    }
}

export async function eachBatchAppsOnEventHandlers(payload: Message[], consumer: IngestionConsumer): Promise<void> {
    const hub = consumer.pluginsServer
    if (!consumer.consumer?.consumer) {
        return // Consumer was closed
    }
    await eachBatchHandlerHelper(
        payload,
        consumer.consumer?.consumer,
        (teamId) => hub.pluginConfigsPerTeam.has(teamId),
        (event) => eachMessageAppsOnEventHandlers(event, hub),
        hub.WORKER_CONCURRENCY * hub.TASKS_PER_WORKER,
        'on_event'
    )
}
