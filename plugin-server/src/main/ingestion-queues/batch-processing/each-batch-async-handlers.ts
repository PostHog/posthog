import { StatsD } from 'hot-shots'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { PostIngestionEvent, RawClickHouseEvent } from '../../../types'
import { DependencyUnavailableError } from '../../../utils/db/error'
import { convertToIngestionEvent, convertToProcessedPluginEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { groupIntoBatches } from '../../../utils/utils'
import { ActionMatcher } from '../../../worker/ingestion/action-matcher'
import { processWebhooksStep } from '../../../worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { silentFailuresAsyncHandlers } from '../../../worker/ingestion/event-pipeline/runner'
import { HookCommander } from '../../../worker/ingestion/hooks'
import { runInstrumentedFunction } from '../../utils'
import { KafkaJSIngestionConsumer } from '../kafka-queue'
import { eachBatch, eachBatchWebhooks } from './each-batch'

export async function eachMessageAppsOnEventHandlers(
    message: KafkaMessage,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
    const event = convertToIngestionEvent(clickHouseEvent)

    await runInstrumentedFunction({
        event: event,
        func: () => queue.workerMethods.runAppsOnEventPipeline(event),
        statsKey: `kafka_queue.process_async_handlers_on_event`,
        timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
        teamId: event.teamId,
    })
}

export async function eachMessageWebhooksHandlers(
    message: KafkaMessage,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander,
    statsd: StatsD | undefined
): Promise<void> {
    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
    const event = convertToIngestionEvent(clickHouseEvent)

    // TODO: previously onEvent and Webhooks were executed in the same process,
    // and onEvent would call convertToProcessedPluginEvent, which ends up
    // mutating the `event` that is passed in. To ensure that we have the same
    // behaviour we run this here, but we should probably refactor this to
    // ensure that we don't mutate the event.
    convertToProcessedPluginEvent(event)

    await runInstrumentedFunction({
        event: event,
        func: () => runWebhooks(statsd, actionMatcher, hookCannon, event),
        statsKey: `kafka_queue.process_async_handlers_webhooks`,
        timeoutMessage: 'After 30 seconds still running runWebhooksHandlersEventPipeline',
        teamId: event.teamId,
    })
}

export async function eachBatchAppsOnEventHandlers(
    payload: EachBatchPayload,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await eachBatch(payload, queue, eachMessageAppsOnEventHandlers, groupIntoBatches, 'async_handlers_on_event')
}

export async function eachBatchWebhooksHandlers(
    payload: EachBatchPayload,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander,
    statsd: StatsD | undefined,
    concurrency: number
): Promise<void> {
    await eachBatchWebhooks(
        payload,
        statsd,
        (message) => eachMessageWebhooksHandlers(message, actionMatcher, hookCannon, statsd),
        groupIntoBatches,
        concurrency,
        'async_handlers_webhooks'
    )
}

async function runWebhooks(
    statsd: StatsD | undefined,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander,
    event: PostIngestionEvent
) {
    const timer = new Date()

    try {
        statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'webhooks' })
        await processWebhooksStep(event, actionMatcher, hookCannon)
        statsd?.increment('kafka_queue.webhooks.processed')
        statsd?.increment('kafka_queue.event_pipeline.step', { step: processWebhooksStep.name })
        statsd?.timing('kafka_queue.event_pipeline.step.timing', timer, { step: processWebhooksStep.name })
    } catch (error) {
        statsd?.increment('kafka_queue.event_pipeline.step.error', { step: processWebhooksStep.name })

        if (error instanceof DependencyUnavailableError) {
            // If this is an error with a dependency that we control, we want to
            // ensure that the caller knows that the event was not processed,
            // for a reason that we control and that is transient.
            status.error('Error processing webhooks', {
                stack: error.stack,
                eventUuid: event.eventUuid,
                teamId: event.teamId,
                error: error,
            })
            throw error
        }

        status.warn(`⚠️`, 'Error processing webhooks, silently moving on', {
            stack: error.stack,
            eventUuid: event.eventUuid,
            teamId: event.teamId,
            error: error,
        })
        silentFailuresAsyncHandlers.inc()
    }
}
