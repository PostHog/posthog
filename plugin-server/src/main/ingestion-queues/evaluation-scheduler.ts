/**
 * Evaluation Scheduler
 *
 * Consumes AI events (e.g., $ai_generation) from the main events stream,
 * matches them against evaluation filters, and triggers evaluation workflows
 * via Temporal when conditions are met.
 */
import * as crypto from 'crypto'
import { Consumer, EachBatchPayload, KafkaMessage } from 'kafkajs'
import { Counter } from 'prom-client'

import { execHog } from '../../cdp/utils/hog-exec'
import { KAFKA_EVENTS_JSON, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { EvaluationManagerService } from '../../llm-analytics/services/evaluation-manager.service'
import { TemporalService } from '../../llm-analytics/services/temporal.service'
import { Evaluation, EvaluationConditionSet } from '../../llm-analytics/types'
import {
    HealthCheckResult,
    HealthCheckResultDegraded,
    HealthCheckResultError,
    HealthCheckResultOk,
    Hub,
    PluginServerService,
    RawKafkaEvent,
} from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'

const evaluationSchedulerEventsProcessed = new Counter({
    name: 'evaluation_scheduler_events_processed',
    help: 'Number of AI events processed by evaluation scheduler',
    labelNames: ['status'],
})

const evaluationMatchesCounter = new Counter({
    name: 'evaluation_matches',
    help: 'Number of evaluation matches by outcome',
    labelNames: ['outcome'], // matched, filtered, sampling_excluded, error
})

// Pure functions for testability

export function filterAndParseMessages(messages: KafkaMessage[]): RawKafkaEvent[] {
    return messages
        .filter((message) => message.headers?.productTrack?.toString('utf8') === 'llma')
        .map((message) => {
            try {
                return parseJSON(message.value!.toString()) as RawKafkaEvent
            } catch (e) {
                logger.error('Error parsing event', { error: e })
                return null
            }
        })
        .filter((event): event is RawKafkaEvent => event !== null)
}

export function groupEventsByTeam(events: RawKafkaEvent[]): Map<number, RawKafkaEvent[]> {
    const grouped = new Map<number, RawKafkaEvent[]>()
    for (const event of events) {
        const teamEvents = grouped.get(event.team_id) || []
        teamEvents.push(event)
        grouped.set(event.team_id, teamEvents)
    }
    return grouped
}

export function checkRolloutPercentage(distinctId: string, rolloutPercentage: number): boolean {
    if (rolloutPercentage >= 100) {
        return true
    }

    // Use MD5 hash for deterministic sampling
    const hash = crypto.createHash('md5').update(distinctId).digest('hex')
    const hashValue = parseInt(hash.substring(0, 8), 16)
    const percentage = (hashValue % 10000) / 100

    return percentage < rolloutPercentage
}

export async function checkConditionMatch(event: RawKafkaEvent, condition: EvaluationConditionSet): Promise<boolean> {
    if (!condition.bytecode) {
        if (condition.bytecode_error) {
            logger.warn('Condition has bytecode error, skipping', {
                conditionId: condition.id,
                error: condition.bytecode_error,
            })
        }
        return false
    }

    // Build globals for HogVM execution
    const filterGlobals = {
        event: event.event,
        elements_chain: event.elements_chain || '',
        distinct_id: event.distinct_id,
        person: {
            properties: {},
        },
        properties: parseJSON(event.properties || '{}'),
    }

    try {
        const execResult = await execHog(condition.bytecode, { globals: filterGlobals })

        if (execResult.error || execResult.execResult?.error) {
            logger.error('Error executing bytecode', {
                conditionId: condition.id,
                error: execResult.error ?? execResult.execResult?.error,
            })
            return false
        }

        return typeof execResult.execResult?.result === 'boolean' && execResult.execResult.result
    } catch (error: unknown) {
        logger.error('Exception executing bytecode', {
            conditionId: condition.id,
            error: error instanceof Error ? error.message : String(error),
        })
        return false
    }
}

export type EvaluationMatchResult =
    | { matched: true; conditionId: string }
    | { matched: false; reason: 'no_conditions' | 'disabled' | 'filtered' | 'sampling_excluded' }

export class EvaluationMatcher {
    async shouldTriggerEvaluation(event: RawKafkaEvent, evaluation: Evaluation): Promise<EvaluationMatchResult> {
        if (!evaluation.enabled) {
            return { matched: false, reason: 'disabled' }
        }

        const conditions = evaluation.conditions as EvaluationConditionSet[]
        if (conditions.length === 0) {
            return { matched: false, reason: 'no_conditions' }
        }

        for (const condition of conditions) {
            const conditionMatched = await checkConditionMatch(event, condition)

            if (!conditionMatched) {
                continue
            }

            const inSample = checkRolloutPercentage(event.distinct_id, condition.rollout_percentage)

            if (!inSample) {
                continue
            }

            return { matched: true, conditionId: condition.id }
        }

        return { matched: false, reason: 'filtered' }
    }
}

export const startEvaluationScheduler = async (hub: Hub): Promise<PluginServerService> => {
    logger.info('🤖', 'Starting evaluation scheduler')

    const { kafka } = hub

    const consumer = kafka.consumer({
        groupId: `${KAFKA_PREFIX}evaluation-scheduler`,
        sessionTimeout: hub.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS,
        rebalanceTimeout: hub.KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS ?? undefined,
        readUncommitted: false,
    })

    setupEventHandlers(consumer)

    const temporalService = new TemporalService(hub)
    const evaluationManager = new EvaluationManagerService(hub)

    await consumer.subscribe({ topic: KAFKA_EVENTS_JSON, fromBeginning: false })
    await consumer.run({
        eachBatch: (payload) => eachBatchEvaluationScheduler(payload, evaluationManager, temporalService),
    })

    const onShutdown = async () => {
        await temporalService.disconnect()
        try {
            await consumer.stop()
        } catch (e) {
            logger.error('🚨', 'Error stopping evaluation scheduler', e)
        }
        try {
            await consumer.disconnect()
        } catch (e) {
            logger.error('🚨', 'Error disconnecting evaluation scheduler', e)
        }
    }

    return {
        id: 'evaluation-scheduler',
        healthcheck: makeHealthCheck(consumer, hub.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS),
        onShutdown,
    }
}

async function eachBatchEvaluationScheduler(
    payload: EachBatchPayload,
    evaluationManager: EvaluationManagerService,
    temporalService: TemporalService
): Promise<void> {
    const { batch, resolveOffset, heartbeat } = payload

    logger.debug('Processing batch', { partition: batch.partition, messageCount: batch.messages.length })

    const aiGenerationEvents = filterAndParseMessages(batch.messages)

    if (aiGenerationEvents.length === 0) {
        resolveOffset(batch.messages[batch.messages.length - 1].offset)
        await commitOffsetsIfNecessary(payload)
        return
    }

    logger.debug('Found $ai_generation events', { count: aiGenerationEvents.length })

    const eventsByTeam = groupEventsByTeam(aiGenerationEvents)
    const teamIds = Array.from(eventsByTeam.keys())

    const evaluationsByTeam = await evaluationManager.getEvaluationsForTeams(teamIds)
    const matcher = new EvaluationMatcher()
    const tasks: Promise<void>[] = []

    for (const [teamId, events] of eventsByTeam.entries()) {
        const evaluations = evaluationsByTeam[teamId] || []

        if (evaluations.length === 0) {
            continue
        }

        for (const event of events) {
            for (const evaluation of evaluations) {
                const task = processEventEvaluationMatch(event, evaluation, matcher, temporalService).catch(
                    (error: unknown) => {
                        logger.error('Error processing evaluation', {
                            evaluationId: evaluation.id,
                            eventUuid: event.uuid,
                            error: error instanceof Error ? error.message : String(error),
                        })
                        evaluationMatchesCounter.labels({ outcome: 'error' }).inc()
                    }
                )

                tasks.push(task)
            }
        }
    }

    const results = await Promise.allSettled(tasks)
    for (const error of results.filter((result): result is PromiseRejectedResult => result.status === 'rejected')) {
        logger.error('Error enqueuing evaluation', {
            error: error.reason instanceof Error ? error.reason.message : String(error.reason),
        })
    }

    resolveOffset(batch.messages[batch.messages.length - 1].offset)
    await commitOffsetsIfNecessary(payload)

    await heartbeat()
}

async function processEventEvaluationMatch(
    event: RawKafkaEvent,
    evaluation: Evaluation,
    matcher: EvaluationMatcher,
    temporalService: TemporalService
): Promise<void> {
    evaluationSchedulerEventsProcessed.labels({ status: 'received' }).inc()

    const result = await matcher.shouldTriggerEvaluation(event, evaluation)

    if (!result.matched) {
        evaluationMatchesCounter.labels({ outcome: result.reason }).inc()
        return
    }

    logger.debug('Evaluation matched', {
        evaluationId: evaluation.id,
        eventUuid: event.uuid,
        conditionId: result.conditionId,
    })

    evaluationMatchesCounter.labels({ outcome: 'matched' }).inc()

    const handle = await temporalService.startEvaluationWorkflow(evaluation.id, event.uuid)

    if (handle) {
        evaluationSchedulerEventsProcessed.labels({ status: 'success' }).inc()
    } else {
        evaluationSchedulerEventsProcessed.labels({ status: 'error' }).inc()
    }
}

async function commitOffsetsIfNecessary(payload: EachBatchPayload): Promise<void> {
    const { commitOffsetsIfNecessary, heartbeat } = payload
    await commitOffsetsIfNecessary()
    await heartbeat()
}

function setupEventHandlers(consumer: Consumer): void {
    const { CONNECT, DISCONNECT, STOP, CRASH, GROUP_JOIN, HEARTBEAT } = consumer.events
    consumer.on(CONNECT, () => logger.info('✅', 'Evaluation scheduler connected'))
    consumer.on(DISCONNECT, () => logger.info('🔌', 'Evaluation scheduler disconnected'))
    consumer.on(STOP, () => logger.info('⏹️', 'Evaluation scheduler stopped'))
    consumer.on(CRASH, ({ payload: { error } }) => logger.error('💥', 'Evaluation scheduler crashed', { error }))
    consumer.on(GROUP_JOIN, ({ payload: { groupId } }) =>
        logger.info('👥', 'Evaluation scheduler joined group', { groupId })
    )
    consumer.on(HEARTBEAT, () => logger.debug('💓', 'Evaluation scheduler heartbeat'))
}

function makeHealthCheck(consumer: Consumer, sessionTimeout: number): () => Promise<HealthCheckResult> {
    const { HEARTBEAT } = consumer.events
    let lastHeartbeat: number = Date.now()
    consumer.on(HEARTBEAT, ({ timestamp }) => (lastHeartbeat = timestamp))

    const isHealthy = async () => {
        const milliSecondsToLastHeartbeat = Date.now() - lastHeartbeat
        if (milliSecondsToLastHeartbeat < sessionTimeout) {
            return new HealthCheckResultOk()
        }

        try {
            const { state } = await consumer.describeGroup()

            if (['CompletingRebalance', 'PreparingRebalance'].includes(state)) {
                return new HealthCheckResultDegraded('Consumer group is rebalancing', { state })
            }

            return new HealthCheckResultOk()
        } catch (error) {
            return new HealthCheckResultError('Error checking consumer group state', { error })
        }
    }
    return isHealthy
}
