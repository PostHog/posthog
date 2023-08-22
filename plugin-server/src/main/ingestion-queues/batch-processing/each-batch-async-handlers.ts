import { StatsD } from 'hot-shots'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { PostIngestionEvent, RawClickHouseEvent } from '../../../types'
import { DependencyUnavailableError } from '../../../utils/db/error'
import { stringToBoolean } from '../../../utils/env-utils'
import { convertToIngestionEvent, convertToProcessedPluginEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { groupIntoBatches } from '../../../utils/utils'
import { ActionMatcher } from '../../../worker/ingestion/action-matcher'
import { processWebhooksStep } from '../../../worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { silentFailuresAsyncHandlers } from '../../../worker/ingestion/event-pipeline/runner'
import { HookCommander } from '../../../worker/ingestion/hooks'
import { runInstrumentedFunction } from '../../utils'
import { KafkaJSIngestionConsumer } from '../kafka-queue'
import { eventDroppedCounter } from '../metrics'
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
    if (!actionMatcher.hasWebhooks(clickHouseEvent.team_id)) {
        // exit early if no webhooks nor resthooks
        return
    }
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

function buildFilterAndGroupFunction(actionMatcher: ActionMatcher) {
    // Most events will not trigger a webhook call, so we want to filter them out as soon as possible
    // to achieve the highest effective concurrency when executing the actual HTTP calls.
    // actionMatcher holds an in-memory set of all teams with enabled webhooks, that we use to
    // drop events based on that signal.
    return function (array: KafkaMessage[], batchSize: number): KafkaMessage[][] {
        const batches: KafkaMessage[][] = []
        let currentBatch: KafkaMessage[] = []

        for (const message of array) {
            const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent
            if (!actionMatcher.hasWebhooks(clickHouseEvent.team_id)) {
                eventDroppedCounter
                    .labels({
                        event_type: 'analytics-webhook',
                        drop_cause: 'no_webhook_action',
                    })
                    .inc()
                continue
            }
            currentBatch.push(message)
            if (currentBatch.length == batchSize) {
                batches.push(currentBatch)
                currentBatch = []
            }
        }
        if (currentBatch) {
            batches.push(currentBatch)
        }
        return batches
    }
}

export async function eachBatchWebhooksHandlers(
    payload: EachBatchPayload,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander,
    statsd: StatsD | undefined,
    concurrency: number
): Promise<void> {
    const filterOutEventsWithoutActions = stringToBoolean(process.env.FILTER_OUT_EVENTS_WITHOUT_ACTION)
    await eachBatchWebhooks(
        payload,
        statsd,
        (message) => eachMessageWebhooksHandlers(message, actionMatcher, hookCannon, statsd),
        filterOutEventsWithoutActions ? buildFilterAndGroupFunction(actionMatcher) : groupIntoBatches,
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
