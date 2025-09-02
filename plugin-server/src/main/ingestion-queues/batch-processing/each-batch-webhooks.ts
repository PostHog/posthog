import { EachBatchPayload, KafkaMessage } from 'kafkajs'
import { Counter } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import type { ActionMatcher } from '~/worker/ingestion/action-matcher'
import type { GroupTypeManager } from '~/worker/ingestion/group-type-manager'
import type { GroupRepository } from '~/worker/ingestion/groups/repositories/group-repository.interface'

import { GroupTypeIndex, GroupTypeToColumnIndex, PostIngestionEvent, RawKafkaEvent, TeamId } from '../../../types'
import { DependencyUnavailableError } from '../../../utils/db/error'
import { convertToPostIngestionEvent } from '../../../utils/event'
import { parseJSON } from '../../../utils/json-parse'
import { logger } from '../../../utils/logger'
import { TeamManager } from '../../../utils/team-manager'
import { pipelineStepErrorCounter, pipelineStepMsSummary } from '../../../worker/ingestion/event-pipeline/metrics'
import { processWebhooksStep } from '../../../worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { HookCommander } from '../../../worker/ingestion/hooks'
import { eventDroppedCounter, latestOffsetTimestampGauge } from '../metrics'
import { ingestEventBatchingBatchCountSummary, ingestEventBatchingInputLengthSummary } from './metrics'

export const silentFailuresAsyncHandlers = new Counter({
    name: 'async_handlers_silent_failure',
    help: 'Number silent failures from async handlers.',
})
// exporting only for testing
export function groupIntoBatchesByUsage(
    array: KafkaMessage[],
    batchSize: number,
    shouldProcess: (teamId: number) => boolean
): { eventBatch: RawKafkaEvent[]; lastOffset: string; lastTimestamp: string }[] {
    // Most events will not trigger a webhook call, so we want to filter them out as soon as possible
    // to achieve the highest effective concurrency when executing the actual HTTP calls.
    // actionMatcher holds an in-memory set of all teams with enabled webhooks, that we use to
    // drop events based on that signal. To use it we must parse the message, as there aren't that many
    // webhooks, we can keep batches of the parsed messages in memory with the offsets of the last message
    const result: { eventBatch: RawKafkaEvent[]; lastOffset: string; lastTimestamp: string }[] = []
    let currentBatch: RawKafkaEvent[] = []
    let currentCount = 0
    array.forEach((message, index) => {
        const clickHouseEvent = parseJSON(message.value!.toString()) as RawKafkaEvent
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
            result.push({ eventBatch: currentBatch, lastOffset: message.offset, lastTimestamp: message.timestamp })
            currentBatch = []
            currentCount = 0
        }
    })
    return result
}

export async function eachBatchWebhooksHandlers(
    payload: EachBatchPayload,
    actionMatcher: ActionMatcher,
    hookCannon: HookCommander,
    concurrency: number,
    groupTypeManager: GroupTypeManager,
    teamManager: TeamManager,
    groupRepository: GroupRepository
): Promise<void> {
    await eachBatchHandlerHelper(
        payload,
        (teamId) => actionMatcher.hasWebhooks(teamId),
        (event) =>
            eachMessageWebhooksHandlers(
                event,
                actionMatcher,
                hookCannon,
                groupTypeManager,
                teamManager,
                groupRepository
            ),
        concurrency,
        'webhooks'
    )
}

export async function eachBatchHandlerHelper(
    payload: EachBatchPayload,
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
    const { batch, resolveOffset, heartbeat, commitOffsetsIfNecessary, isRunning, isStale }: EachBatchPayload = payload

    const batchesWithOffsets = groupIntoBatchesByUsage(batch.messages, concurrency, shouldProcess)

    ingestEventBatchingInputLengthSummary.observe(batch.messages.length)
    ingestEventBatchingBatchCountSummary.observe(batchesWithOffsets.length)

    for (const { eventBatch, lastOffset, lastTimestamp } of batchesWithOffsets) {
        if (!isRunning() || isStale()) {
            logger.info('🚪', `Bailing out of a batch of ${batch.messages.length} events (${loggingKey})`, {
                isRunning: isRunning(),
                isStale: isStale(),
                msFromBatchStart: new Date().valueOf() - batchStartTimer.valueOf(),
            })
            await heartbeat()
            return
        }

        await Promise.all(
            eventBatch.map((event: RawKafkaEvent) => eachMessageHandler(event).finally(() => heartbeat()))
        )

        resolveOffset(lastOffset)
        await commitOffsetsIfNecessary()

        // Record that latest messages timestamp, such that we can then, for
        // instance, alert on if this value is too old.
        latestOffsetTimestampGauge
            .labels({ partition: batch.partition, topic: batch.topic, groupId: key })
            .set(Number.parseInt(lastTimestamp))

        await heartbeat()
    }

    logger.debug(
        '🧩',
        `Kafka batch of ${batch.messages.length} events completed in ${
            new Date().valueOf() - batchStartTimer.valueOf()
        }ms (${loggingKey})`
    )
}

async function addGroupPropertiesToPostIngestionEvent(
    event: PostIngestionEvent,
    groupTypeManager: GroupTypeManager,
    teamManager: TeamManager,
    groupRepository: GroupRepository
): Promise<PostIngestionEvent> {
    let groupTypes: GroupTypeToColumnIndex | null = null
    if (await teamManager.hasAvailableFeature(event.teamId, 'group_analytics')) {
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

            const group = await groupRepository.fetchGroup(
                event.teamId as TeamId,
                columnIndex as GroupTypeIndex,
                groupKey
            )

            const groupProperties = group ? group.group_properties : {}

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
    teamManager: TeamManager,
    groupRepository: GroupRepository
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
        teamManager,
        groupRepository
    )

    await instrumentFn(
        {
            key: `kafka_queue.process_async_handlers_webhooks`,
            getLoggingContext: () => ({
                event: JSON.stringify(event),
            }),
        },
        () => runWebhooks(actionMatcher, hookCannon, event)
    )
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
            logger.error('Error processing webhooks', {
                stack: error.stack,
                eventUuid: event.eventUuid,
                teamId: event.teamId,
                error: error,
            })
            throw error
        }

        logger.warn(`⚠️`, 'Error processing webhooks, silently moving on', {
            stack: error.stack,
            eventUuid: event.eventUuid,
            teamId: event.teamId,
            error: error,
        })
        silentFailuresAsyncHandlers.inc()
    }
}
