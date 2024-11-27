import * as Sentry from '@sentry/node'
import { storeOffsetsForMessages } from 'kafka/consumer'
import { KafkaConsumer, Message } from 'node-rdkafka'
import { QueryResult } from 'pg'
import { Counter } from 'prom-client'
import { ActionMatcher } from 'worker/ingestion/action-matcher'
import { GroupTypeManager } from 'worker/ingestion/group-type-manager'
import { OrganizationManager } from 'worker/ingestion/organization-manager'

import { GroupTypeToColumnIndex, PostIngestionEvent, RawKafkaEvent } from '../../../types'
import { DependencyUnavailableError } from '../../../utils/db/error'
import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'
import { convertToPostIngestionEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { pipelineStepErrorCounter, pipelineStepMsSummary } from '../../../worker/ingestion/event-pipeline/metrics'
import { processWebhooksStep } from '../../../worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { HookCommander } from '../../../worker/ingestion/hooks'
import { runInstrumentedFunction } from '../../utils'
import { eventDroppedCounter } from '../metrics'
import { ingestEventBatchingBatchCountSummary, ingestEventBatchingInputLengthSummary } from './metrics'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export const silentFailuresAsyncHandlers = new Counter({
    name: 'async_handlers_silent_failure',
    help: 'Number silent failures from async handlers.',
})
// exporting only for testing
export function groupIntoBatchesByUsage(
    array: Message[],
    batchSize: number,
    shouldProcess: (teamId: number) => boolean
): { eventBatch: RawKafkaEvent[] }[] {
    // Most events will not trigger a webhook call, so we want to filter them out as soon as possible
    // to achieve the highest effective concurrency when executing the actual HTTP calls.
    // actionMatcher holds an in-memory set of all teams with enabled webhooks, that we use to
    // drop events based on that signal. To use it we must parse the message, as there aren't that many
    // webhooks, we can keep batches of the parsed messages in memory with the offsets of the last message
    const result: { eventBatch: RawKafkaEvent[] }[] = []
    let currentBatch: RawKafkaEvent[] = []
    let currentCount = 0
    array.forEach((message, index) => {
        const clickHouseEvent = JSON.parse(message.value!.toString()) as RawKafkaEvent
        if (shouldProcess(clickHouseEvent.team_id)) {
            currentBatch.push(clickHouseEvent)
            currentCount++
        } else {
            eventDroppedCounter
                .labels({
                    event_type: 'analytics-webhook',
                    drop_cause: 'no_matching_action',
                })
                .inc()
        }
        if (currentCount === batchSize || index === array.length - 1) {
            result.push({ eventBatch: currentBatch })
            currentBatch = []
            currentCount = 0
        }
    })
    return result
}

export async function eachBatchWebhooksHandlers(
    payload: Message[],
    consumer: KafkaConsumer,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander,
    concurrency: number,
    groupTypeManager: GroupTypeManager,
    organizationManager: OrganizationManager,
    postgres: PostgresRouter
): Promise<void> {
    await eachBatchHandlerHelper(
        payload,
        consumer,
        (teamId) => actionMatcher.hasWebhooks(teamId),
        (event) =>
            eachMessageWebhooksHandlers(
                event,
                actionMatcher,
                hookCannon,
                groupTypeManager,
                organizationManager,
                postgres
            ),
        concurrency,
        'webhooks'
    )
}

export async function eachBatchHandlerHelper(
    messages: Message[],
    consumer: KafkaConsumer,
    shouldProcess: (teamId: number) => boolean,
    eachMessageHandler: (event: RawKafkaEvent) => Promise<void>,
    concurrency: number,
    stats_key: string
): Promise<void> {
    // similar to eachBatch function in each-batch.ts, but without the dependency on the KafkaJSIngestionConsumer
    // & handling the different batching return type
    const key = `async_handlers_${stats_key}`
    const batchStartTimer = new Date()
    const loggingKey = `each_batch_${key}`

    const transaction = Sentry.startTransaction({ name: `eachBatch${stats_key}` })

    try {
        const batches = groupIntoBatchesByUsage(messages, concurrency, shouldProcess)

        ingestEventBatchingInputLengthSummary.observe(messages.length)
        ingestEventBatchingBatchCountSummary.observe(batches.length)

        for (const { eventBatch } of batches) {
            const batchSpan = transaction.startChild({ op: 'messageBatch', data: { batchLength: eventBatch.length } })

            await Promise.all(eventBatch.map((event: RawKafkaEvent) => eachMessageHandler(event)))
            batchSpan.finish()
        }
        storeOffsetsForMessages(messages, consumer)
        status.debug(
            '🧩',
            `Kafka batch of ${messages.length} events completed in ${
                new Date().valueOf() - batchStartTimer.valueOf()
            }ms (${loggingKey})`
        )
    } finally {
        transaction.finish()
    }
}

async function addGroupPropertiesToPostIngestionEvent(
    event: PostIngestionEvent,
    groupTypeManager: GroupTypeManager,
    organizationManager: OrganizationManager,
    postgres: PostgresRouter
): Promise<PostIngestionEvent> {
    let groupTypes: GroupTypeToColumnIndex | undefined = undefined
    if (await organizationManager.hasAvailableFeature(event.teamId, 'group_analytics')) {
        // If the organization has group analytics enabled then we enrich the event with group data
        groupTypes = await groupTypeManager.fetchGroupTypes(event.projectId)
    }

    let groups: PostIngestionEvent['groups'] = undefined
    if (groupTypes) {
        groups = {}

        for (const [groupType, columnIndex] of Object.entries(groupTypes)) {
            const groupKey = (event.properties[`$groups`] || {})[groupType]
            if (!groupKey) {
                continue
            }

            const queryString = `SELECT group_properties FROM posthog_group WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3`

            const selectResult: QueryResult = await postgres.query(
                PostgresUse.COMMON_READ,
                queryString,
                [event.teamId, columnIndex, groupKey],
                'fetchGroup'
            )

            const groupProperties = selectResult.rows.length > 0 ? selectResult.rows[0].group_properties : {}

            if (groupKey && groupProperties) {
                groups[groupType] = {
                    index: columnIndex,
                    key: groupKey,
                    type: groupType,
                    properties: groupProperties,
                }
            }
        }
    }

    return {
        ...event,
        groups,
    }
}

export async function eachMessageWebhooksHandlers(
    kafkaEvent: RawKafkaEvent,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander,
    groupTypeManager: GroupTypeManager,
    organizationManager: OrganizationManager,
    postgres: PostgresRouter
): Promise<void> {
    if (!actionMatcher.hasWebhooks(kafkaEvent.team_id)) {
        // exit early if no webhooks nor resthooks
        return
    }

    const eventWithoutGroups = convertToPostIngestionEvent(kafkaEvent)
    // This is very inefficient, we always pull group properties for all groups (up to 5) for this event
    // from PG if a webhook is defined for this team.
    // Instead we should be lazily loading group properties only when needed, but this is the fastest way to fix this consumer
    // that will be deprecated in the near future by CDP/Hog
    const event = await addGroupPropertiesToPostIngestionEvent(
        eventWithoutGroups,
        groupTypeManager,
        organizationManager,
        postgres
    )

    await runInstrumentedFunction({
        func: () => runWebhooks(actionMatcher, hookCannon, event),
        statsKey: `kafka_queue.process_async_handlers_webhooks`,
        timeoutMessage: 'After 30 seconds still running runWebhooksHandlersEventPipeline',
        timeoutContext: () => ({
            event: JSON.stringify(event),
        }),
        teamId: event.teamId,
    })
}

async function runWebhooks(actionMatcher: ActionMatcher, hookCannon: HookCommander, event: PostIngestionEvent) {
    const timer = new Date()

    try {
        await processWebhooksStep(event, actionMatcher, hookCannon)
        pipelineStepMsSummary.labels('processWebhooksStep').observe(Date.now() - timer.getTime())
    } catch (error) {
        pipelineStepErrorCounter.labels('processWebhooksStep').inc()

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
