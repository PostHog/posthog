import { EachBatchPayload } from 'kafkajs'

import { PluginMethod, PostIngestionEvent, RawClickHouseEvent } from '../../../types'
import { convertToIngestionEvent } from '../../../utils/event'
import {
    processComposeWebhookStep,
    processOnEventStep,
} from '../../../worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { runInstrumentedFunction } from '../../utils'
import { KafkaJSIngestionConsumer } from '../kafka-queue'
import { eventDroppedCounter } from '../metrics'
import { eachBatchHandlerHelper } from './each-batch-webhooks'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export async function handleOnEventPlugins(event: PostIngestionEvent, queue: KafkaJSIngestionConsumer): Promise<void> {
    await runInstrumentedFunction({
        func: () => processOnEventStep(queue.pluginsServer, event),
        statsKey: `kafka_queue.process_async_handlers_on_event`,
        timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
        timeoutContext: () => ({
            event: JSON.stringify(event),
        }),
        teamId: event.teamId,
    })
}

export async function handleComposeWebhookPlugins(
    event: PostIngestionEvent,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await runInstrumentedFunction({
        func: () => processComposeWebhookStep(queue.pluginsServer, event),
        statsKey: `kafka_queue.process_async_handlers_on_event`,
        timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
        timeoutContext: () => ({
            event: JSON.stringify(event),
        }),
        teamId: event.teamId,
    })
}

export async function eachMessageAppsOnEventHandlers(
    clickHouseEvent: RawClickHouseEvent,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    const pluginConfigs = queue.pluginsServer.pluginConfigsPerTeam.get(clickHouseEvent.team_id)
    if (pluginConfigs) {
        const onEventPlugins = pluginConfigs.filter((pluginConfig) => pluginConfig.method === PluginMethod.onEvent)

        // TODO: Ask about this - still unclear why and when this gets set
        // Elements parsing can be extremely slow, so we skip it for some plugins that are manually marked
        // # SKIP_ELEMENTS_PARSING_PLUGINS
        const skipElementsChain = onEventPlugins
            .filter((pluginConfig) => pluginConfig.method === PluginMethod.onEvent)
            .every((pluginConfig) => queue.pluginsServer.pluginConfigsToSkipElementsParsing?.(pluginConfig.plugin_id))

        const event = convertToIngestionEvent(clickHouseEvent, skipElementsChain)

        await Promise.all([handleOnEventPlugins(event, queue), handleComposeWebhookPlugins(event, queue)])
    } else {
        eventDroppedCounter
            .labels({
                event_type: 'onevent',
                drop_cause: 'no_matching_plugin',
            })
            .inc()
    }
}

export async function eachBatchAppsOnEventHandlers(
    payload: EachBatchPayload,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await eachBatchHandlerHelper(
        payload,
        (teamId) => queue.pluginsServer.pluginConfigsPerTeam.has(teamId),
        (event) => eachMessageAppsOnEventHandlers(event, queue),
        queue.pluginsServer.WORKER_CONCURRENCY * queue.pluginsServer.TASKS_PER_WORKER,
        'on_event'
    )
}
